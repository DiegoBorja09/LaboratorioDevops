# GCP: service-a en Cloud Run

service-a corre en Cloud Run, en `us-east1`, junto al service-b de AWS `us-east-1`. El servicio escala a cero, admite como máximo una instancia y no usa balanceador, dominio, VPC, NAT, Cloud SQL ni IP fija. data-service, en el apartado final, sí usa una VPC propia, Cloud NAT y Cloud SQL, y permanece apagado mientras sus variables están en `false`.

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

## Integrador: data-service

Estos recursos nacen apagados. No cambies `create_service`. Volver a poner un interruptor en `false` y aplicar destruye solo lo que ese interruptor creó.

| Variable | Default | Qué crea |
| --- | --- | --- |
| `create_integrator_foundation` | `false` | VPC `otel-lab-integrator`, subred `10.80.0.0/24`, Flow Logs, Cloud Router, IP estática, Cloud NAT, Cloud SQL, secretos y la cuenta `otel-lab-data-service` |
| `create_data_service` | `false` | Cloud Run privado `otel-multicloud-lab-data-service` |
| `create_data_migration_job` | `false` | Cloud Run Job `otel-multicloud-lab-data-migrate`, sin ejecutarlo |
| `data_service_image_tag` | `lab` | Solo entra en la URL de la imagen |

La subred `10.80.0.0/24` no coincide con la red default de GCP ni con `172.31.0.0/16` de la VPC default de AWS. Tiene Private Google Access y Flow Logs cada 30 segundos, con muestreo `0.5` y metadatos incluidos. El intervalo corto es para ver tráfico durante el laboratorio; el volumen es bajo y la red es temporal. No hay Serverless VPC Access Connector: Cloud Run usa Direct VPC Egress y `ALL_TRAFFIC`, para que RDS vea la IP de Cloud NAT.

Cloud SQL es PostgreSQL 16, `db-f1-micro`, zonal, disco SSD de 10 GB sin crecimiento automático y sin alta disponibilidad. Los backups y la recuperación a un punto en el tiempo quedan apagados: es un laboratorio temporal y esa es la opción más barata; no hay protección ante un borrado accidental. `deletion_protection` está en `false`. La instancia puede tener IPv4 pública, pero no tiene redes autorizadas: no se abre `0.0.0.0/0`. data-service entra por el socket `/cloudsql` con la cuenta `roles/cloudsql.client`. Las conexiones directas, si alguien las habilitara, exigirían SSL.

La contraseña de `data_service` sale de `random_password` y se guarda, ya dentro de la URL `postgresql+asyncpg`, en el secreto `data-service-gcp-database-url`. `CHAOS_TOKEN` se genera igual y vive en `data-service-chaos-token`. Ninguno de los dos se exporta. `data-service-aws-database-url` se crea vacío: la versión la agrega `scripts/provision-integrator-secrets.ps1` después de RDS. La cuenta `otel-lab-data-service` solo lee esos secretos y el secreto del collector. Además tiene `roles/logging.logWriter`, `roles/monitoring.metricWriter` y `roles/cloudtrace.agent`, los mismos roles de telemetría que service-a. No recibe `roles/secretmanager.secretAccessor` de proyecto.

La imagen reutiliza el repositorio `otel-multicloud-lab`:

```text
us-east1-docker.pkg.dev/<project>/otel-multicloud-lab/data-service:lab
```

`terraform output -raw data_service_image_url` imprime la URL real del proyecto. Terraform no construye ni publica la imagen.

Cloud Run, cuando `create_data_service` pasa a `true`, usa 1 vCPU y 512 MiB por contenedor, escala de 0 a 1 y monta Cloud SQL en `/cloudsql`. El sidecar es el mismo collector `0.162.0` y el mismo secreto de configuración que service-a. El servicio no tiene binding `allUsers`. El único `roles/run.invoker` es la cuenta de service-a. `DATA_SERVICE_URL` no se escribe todavía en service-a. `DATA_SERVICE_SKIP_MIGRATIONS=true` evita que el arranque de la revisión ejecute Alembic.

El plan de Cloud Run lee la última versión de `data-service-aws-database-url`. Sin esa versión, la fase del servicio se detiene. Con `create_data_service = false` la fundación se puede aplicar aunque el secreto siga vacío.

Cuando `create_data_service` y la fundación están activos, service-a recibe `DATA_SERVICE_URL` y `DATA_SERVICE_AUDIENCE` con la URL base de data-service, y `DATA_SERVICE_AUTH_ENABLED=true`. Esas variables no se agregan si data-service no existe, así que no hay un índice inválido ni una dependencia circular: data-service no referencia el recurso de service-a. El binding `roles/run.invoker` sigue siendo solo la cuenta de service-a. data-service no pasa a ser público.

El job usa la misma imagen, los dos secretos de base, el socket y la misma salida por Cloud NAT. Su comando es el entrypoint, que migra primero Cloud SQL y después RDS, y luego termina. Alembic se puede repetir. `terraform apply` crea el job y no lo ejecuta.

### Orden

No pegues estos comandos con valores reales. Edita el `terraform.tfvars` que ya existe; no lo sustituyas por el ejemplo.

1. Fundación, sin Cloud Run:

```powershell
# create_integrator_foundation = true
# create_data_service = false
# create_data_migration_job = false
terraform -chdir=infrastructure/gcp plan
terraform -chdir=infrastructure/gcp apply
terraform -chdir=infrastructure/gcp output -raw cloud_run_egress_cidr
```

El output es una IPv4 `/32`, por ejemplo la forma `203.0.113.10/32`.

2. Con ese CIDR, crea RDS en AWS. El procedimiento está en `infrastructure/aws/README.md`.

3. Desde la raíz del repositorio Git:

```powershell
.\otel-multicloud-lab\scripts\provision-integrator-secrets.ps1 -GcpProjectId PROYECTO -GcpRegion us-east1 -AwsRegion us-east-1
gcloud secrets versions list data-service-aws-database-url --project PROYECTO --filter="state=ENABLED" --limit=1
```

El script no imprime la URL ni la contraseña. El listado solo muestra el nombre de la versión.

4. Publica la imagen. No forma parte de Terraform:

```powershell
$image = terraform -chdir=infrastructure/gcp output -raw data_service_image_url
gcloud auth configure-docker us-east1-docker.pkg.dev
docker build --platform linux/amd64 --tag $image services/data-service
docker push $image
```

5. Servicio y job, todavía sin ejecutar la migración:

```powershell
# create_data_service = true
# create_data_migration_job = true
terraform -chdir=infrastructure/gcp plan
terraform -chdir=infrastructure/gcp apply
gcloud run jobs execute otel-multicloud-lab-data-migrate --project PROYECTO --region us-east1 --wait
```

6. `/health` y `/ready` con un identity token. No guardes el token. Una cuenta sin permiso de invocación recibe 403. El binding permanente es solo la cuenta de service-a; un Owner del proyecto también puede invocar. No agregues `allUsers`.

```powershell
$url = terraform -chdir=infrastructure/gcp output -raw data_service_url
$token = gcloud auth print-identity-token
curl.exe -H "Authorization: Bearer $token" "$url/health"
curl.exe -H "Authorization: Bearer $token" "$url/ready"
```

`/ready` necesita las dos bases y la migración ya aplicada.

### Destrucción, al revés

No pongas `create_service` en `false`: eso borraría service-a.

1. `create_data_service = false` y `create_data_migration_job = false`. Aplica GCP. Desaparece Cloud Run y el job.
2. `create_integrator_data = false` en AWS y aplica. Desaparece RDS, sin snapshot final.
3. `create_integrator_foundation = false` y aplica GCP. Desaparecen Cloud SQL, los tres secretos de data-service, la cuenta, Cloud NAT, la IP estática y la VPC.
4. En las consolas, confirma que no quedan discos, snapshots, la IP estática ni secretos de data-service. Las APIs del proyecto siguen habilitadas. Cloud SQL sin backups no debería dejar copias; revísalo igual porque la instancia factura mientras existe.

Volver a `false` y aplicar destruye esos recursos. La próxima fundación genera otra contraseña y otro token.
