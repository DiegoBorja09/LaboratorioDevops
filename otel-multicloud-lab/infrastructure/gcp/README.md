# GCP: service-a en Cloud Run

service-a corre en Cloud Run, en `us-east1`, junto al service-b de AWS `us-east-1`. El servicio escala a cero, admite como máximo una instancia y no usa balanceador, dominio, VPC, NAT, Cloud SQL ni IP fija.

Un sidecar del Google-Built OpenTelemetry Collector `0.162.0` escucha OTLP solo en `localhost:4317` y `localhost:4318`. Su health check está en `0.0.0.0:13133`. Los pipelines de trazas, métricas y logs exportan solo a Grafana Cloud por OTLP HTTP. El exporter hacia `telemetry.googleapis.com` salió de esos pipelines para evitar los fallos por IPv6. El token entra en Secret Manager al aplicar, no en Git.

## Requisitos

- Terraform `>= 1.10` (el pipeline usa 1.16.5)
- Google Cloud CLI con una sesión del proyecto `otel-multicloud-lab-75147`
- Docker, para publicar `service-a` en `linux/amd64`
- Permiso para habilitar APIs, crear Artifact Registry, Secret Manager, IAM y Cloud Run
- `iam.serviceAccountUser` sobre la cuenta `otel-lab-service-a` para quien ejecuta el apply de la fase 2

La autenticación de Terraform sale de Application Default Credentials. No pongas llaves JSON ni tokens en este directorio.

```powershell
gcloud config set project otel-multicloud-lab-75147
gcloud auth application-default login
```

Los comandos siguientes se ejecutan desde `otel-multicloud-lab`.

```powershell
Copy-Item infrastructure\gcp\terraform.tfvars.example infrastructure\gcp\terraform.tfvars
terraform -chdir=infrastructure/gcp init
```

`terraform.tfvars` está ignorado por Git. El ejemplo no lleva secretos. Deja `create_service = false` hasta haber publicado la imagen.

## Fase 1. Registro, identidad y configuración

Con `create_service = false` el apply habilita las APIs y no las deshabilita al destruir. Crea el repositorio Docker privado `otel-multicloud-lab`, la cuenta de servicio y el secreto del collector. No crea Cloud Run.

Las políticas de limpieza borran versiones antiguas y conservan las 3 más recientes de cada paquete.

La cuenta `otel-lab-service-a` recibe solo estos roles de proyecto:

- `roles/logging.logWriter`
- `roles/monitoring.metricWriter`
- `roles/cloudtrace.agent`
- `roles/secretmanager.secretAccessor`

```powershell
terraform -chdir=infrastructure/gcp apply
```

Publica service-a antes de la fase 2:

```powershell
$image = terraform -chdir=infrastructure/gcp output -raw service_a_image_url
gcloud auth configure-docker us-east1-docker.pkg.dev
docker build --platform linux/amd64 --tag $image services/service-a
docker push $image
```

Si cambias `service_a_image_tag`, vuelve a leer el output antes de construir.

## Fase 2. Cloud Run

En `infrastructure/gcp/terraform.tfvars` deja `create_service = true`, pon en `service_b_url` la URL de service-b, por ejemplo `http://IP_PUBLICA:8082`, y sustituye `grafana_otlp_endpoint` y `grafana_otlp_auth` por los valores de tu stack. Sin la URL de service-b o con los placeholders de Grafana, el plan se detiene.

Revisa el plan y crea el servicio:

```powershell
terraform -chdir=infrastructure/gcp plan
terraform -chdir=infrastructure/gcp apply
```

El servicio se llama `otel-multicloud-lab-service-a`. service-a escucha en el puerto 8080 y espera a que el collector pase el startup probe de `13133`. El tráfico de demostración es público, sin autenticación, mediante `roles/run.invoker` para `allUsers`.

Comprueba la salud:

```powershell
$url = terraform -chdir=infrastructure/gcp output -raw service_a_url
curl.exe "$url/health"
```

La respuesta esperada contiene `"status":"healthy"` y `"service":"service-a"`.

Al terminar:

```powershell
terraform -chdir=infrastructure/gcp destroy
```

`destroy` borra Cloud Run, el repositorio, el secreto y la cuenta. Las APIs permanecen habilitadas.

## Grafana Cloud

El exporter `otlphttp/grafana` es el único destino de los pipelines. Terraform sustituye `grafana_otlp_endpoint` y `grafana_otlp_auth` en el secreto del collector. El nombre del componente sigue siendo `otlphttp`: el collector 0.162.0 no registra `otlp_http`. `grafana_otlp_auth` es sensible y no se versiona.

service-a publica `service.name=service-a`, `service.namespace=otel-multicloud-lab`, `service.version=1.0.0` y `deployment.environment=gcp` mediante `DEPLOYMENT_ENVIRONMENT`. Hay que reconstruir y publicar la imagen antes del apply de la fase 2, porque el atributo se resuelve dentro del proceso.

En Grafana Cloud abre el stack, entra a OpenTelemetry o Connections y copia el endpoint OTLP que termina en `/otlp`. No agregues `/v1/traces`. El header es `Basic` más el base64 de `instance-id:token`. El token necesita permiso de escritura de métricas, logs y trazas.

Calcula el header en la sesión local y pégalo solo en `infrastructure/gcp/terraform.tfvars`:

```powershell
$instanceId = Read-Host "Instance ID de Grafana Cloud"
$secure = Read-Host "Token de Grafana Cloud" -AsSecureString
$token = [System.Net.NetworkCredential]::new("", $secure).Password
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${instanceId}:${token}"))
Write-Output "grafana_otlp_auth = `"Basic $basic`""
```

Copia esa línea al `terraform.tfvars` ignorado por Git. Sustituye también el endpoint de ejemplo. Antes de la fase 2 las dos variables tienen que dejar de ser los placeholders `example.invalid` y `REPLACE_WITH`.

Para ver la telemetría, llama al servicio y abre Explore en Grafana Cloud:

```powershell
curl.exe "$url/health"
```

- Traces: origen Tempo. Busca el servicio `service-a`.
- Logs: origen Loki. Consulta `{service_name="service-a"}`.
- Metrics: origen Prometheus o Mimir. Busca `app_orders_requests` o `app.orders.requests`.

Un `POST /api/v1/orders` deja más spans, logs y la métrica de duración. El envío a Google Cloud sigue activo.

Cada contenedor usa 1 vCPU y 512 MiB. Cloud Run de segunda generación, necesaria para el sidecar, no baja de ese piso por contenedor, así que la instancia suma 2 vCPU y 1 GiB. `min_instance_count = 0` y CPU solo durante la petición dejan el costo en cero mientras nadie llama al servicio. El timeout de la revisión es 60 segundos. No actives el boost de CPU de arranque: acorta el cold start y se factura aparte.

## Supuestos

- El proyecto `otel-multicloud-lab-75147` existe y tiene facturación.
- La política de la organización permite `allUsers` en Cloud Run. Si Domain Restricted Sharing lo bloquea, el apply de la fase 2 falla en el binding público.
- Quien aplica puede usar la cuenta de servicio (`roles/iam.serviceAccountUser`).
- El agente `serverless-robot-prod` recibe `roles/artifactregistry.reader` solo sobre este repositorio, para que Cloud Run descargue la imagen. Esa identidad no es la cuenta de service-a.
- Cloud Run no define `GOOGLE_CLOUD_PROJECT`. El sidecar recibe esa variable para que el procesador `resource/gcp_project_id` rellene el atributo.
- El Dockerfile de service-a ya escucha en `0.0.0.0:8080`. No hizo falta cambiarlo.
- El probe oficial usa timeout y periodo de 30 segundos. Terraform exige que el timeout sea menor que el periodo, así que quedaron en 10 y 30 segundos.
- El pipeline solo ejecuta `fmt`, `init -backend=false` y `validate`. No inicia sesión en GCP.
- `grafana_otlp_auth` es sensible. El ejemplo versionado usa un placeholder que el plan rechaza cuando `create_service` es true.
