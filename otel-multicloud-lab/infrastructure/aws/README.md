# AWS: laboratorio de mínimo costo

Una instancia EC2 en `us-east-1` corre tres contenedores sobre una red Docker privada llamada `otel-lab`:

1. `postgres:16-alpine`, sin puerto publicado en el host.
2. AWS Distro for OpenTelemetry Collector `v0.50.0`. OTLP queda solo en la red Docker.
3. `service-b`, publicado en el host como TCP `8082` hacia el `8080` del contenedor.

RDS para data-service es opcional y queda apagado mientras `create_integrator_data` es `false`. La instancia de service-b usa la VPC predeterminada y una subred pública que ya asigna IPv4 pública. El disco raíz es gp3, cifrado y de 8 GB. No hay llave SSH: el rol de instancia incluye `AmazonSSMManagedInstanceCore`. El grupo de seguridad acepta desde Internet únicamente TCP 8082. La salida queda abierta para que la instancia llegue a Systems Manager, ECR, Docker Hub, CloudWatch y X-Ray sin NAT Gateway ni endpoints de VPC.

El repositorio ECR `otel-multicloud-lab-service-b` es privado, escanea cada imagen al publicarla y conserva como máximo 3. La contraseña de PostgreSQL sale de `random_password`, no de un archivo. Terraform la marca sensible y la inyecta en `user_data`. El state queda fuera de Git.

El collector envía trazas a X-Ray y métricas y logs al grupo `/otel-multicloud-lab/university-lab`, con retención de 1 día. Las métricas viajan como Embedded Metric Format dentro de ese grupo. Los mismos pipelines también exportan a Grafana Cloud por OTLP HTTP. Terraform escribe el endpoint y el header en la configuración del collector al aplicar. El token no entra en Git. El rol de la instancia solo puede leer la imagen de este repositorio y escribir en ese grupo y en X-Ray.

## Requisitos

- Terraform `>= 1.10` (el pipeline usa 1.16.5)
- AWS CLI con credenciales de la cuenta del laboratorio
- Docker, para construir `service-b` en `linux/amd64`
- Una VPC predeterminada en `us-east-1` con al menos una subred pública

Comprueba la sesión antes de aplicar:

```powershell
aws sts get-caller-identity
```

`create_instance` separa las dos fases. En `false` Terraform crea únicamente el repositorio ECR y su política de retención. En `true` agrega la instancia y lo que ella necesita: rol, grupo de logs y grupo de seguridad. El ejemplo versionado deja la variable en `false`.

Los comandos siguientes se ejecutan desde la carpeta `otel-multicloud-lab`.

```powershell
Copy-Item infrastructure\aws\terraform.tfvars.example infrastructure\aws\terraform.tfvars
terraform -chdir=infrastructure/aws init
```

`terraform.tfvars` no lleva contraseñas y Git lo ignora. Con `create_instance = true`, `random_password` genera la contraseña dentro del state.

## Fase 1. Publicar la imagen

La instancia descarga `service-b` desde ECR. El repositorio tiene que existir y contener la etiqueta `lab` antes de crear la EC2. Deja `create_instance = false`.

1. Crear únicamente ECR:

```powershell
terraform -chdir=infrastructure/aws apply
```

2. Construir y publicar service-b:

```powershell
$repository = terraform -chdir=infrastructure/aws output -raw ecr_repository_url
$registry = $repository.Split("/")[0]
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $registry
docker build --platform linux/amd64 --tag "${repository}:lab" services/service-b
docker push "${repository}:lab"
```

Si cambias `service_b_image_tag`, usa esa etiqueta en `--tag` y en `docker push`.

## Fase 2. Crear la instancia y apagarla

En `infrastructure/aws/terraform.tfvars` cambia `create_instance` a `true` y sustituye `grafana_otlp_endpoint` y `grafana_otlp_auth`. No vuelvas a dejar `create_instance` en `false` mientras la instancia exista: un apply posterior la eliminaría. Con los placeholders de Grafana el plan se detiene.

3. Revisar el plan completo:

```powershell
terraform -chdir=infrastructure/aws plan
```

El plan debe incluir la EC2, el rol, el grupo de logs y el grupo de seguridad, además del ECR que ya existe.

4. Crear EC2:

```powershell
terraform -chdir=infrastructure/aws apply
```

El primer arranque instala Docker, descarga las tres imágenes y espera a PostgreSQL. Puede tardar varios minutos. `/health` consulta la base, así que responde cuando las migraciones terminaron.

5. Verificar `/health`:

```powershell
curl.exe (terraform -chdir=infrastructure/aws output -raw service_b_health_url)
```

La respuesta esperada contiene `"status":"healthy"` y `"database":"connected"`.

Si no responde, la consola de la instancia está en Systems Manager, sin SSH:

```powershell
aws ssm start-session --target (terraform -chdir=infrastructure/aws output -raw ec2_instance_id)
```

Dentro de la sesión:

```bash
sudo tail -n 200 /var/log/otel-lab-user-data.log
sudo docker ps
```

6. Ejecutar `terraform destroy` al terminar. El puerto 8082 queda abierto a Internet y `t3.small` sigue facturando mientras la instancia exista.

```powershell
terraform -chdir=infrastructure/aws destroy
```

`force_delete` del repositorio permite borrar ECR aunque todavía tenga imágenes. El disco se elimina con la instancia. X-Ray conserva las trazas ya enviadas hasta su retención habitual; este código no crea un grupo de X-Ray.

## Grafana Cloud

El exporter `otlphttp/grafana` se suma a X-Ray, EMF y CloudWatch Logs. Terraform sustituye `grafana_otlp_endpoint` y `grafana_otlp_auth` en el YAML que arranca el collector. El componente se llama `otlphttp` porque ADOT 0.50.0 no registra `otlp_http`. `grafana_otlp_auth` es sensible. No lo pongas en el ejemplo ni en el script versionado.

service-b publica `service.name=service-b`, `service.namespace=otel-multicloud-lab`, `service.version=1.0.0` y `deployment.environment=aws`. Reconstruye y publica la imagen `lab` antes de crear la EC2: el atributo se resuelve en el código del servicio.

En Grafana Cloud copia el endpoint OTLP que termina en `/otlp`, sin `/v1/traces`. El header es `Basic` más el base64 de `instance-id:token`. El token necesita permiso de escritura de métricas, logs y trazas.

```powershell
$instanceId = Read-Host "Instance ID de Grafana Cloud"
$secure = Read-Host "Token de Grafana Cloud" -AsSecureString
$token = [System.Net.NetworkCredential]::new("", $secure).Password
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${instanceId}:${token}"))
Write-Output "grafana_otlp_auth = `"Basic $basic`""
```

Pega el endpoint y esa línea en `infrastructure/aws/terraform.tfvars`. Ese archivo está ignorado. Sustituye los placeholders `example.invalid` y `REPLACE_WITH` antes de crear la EC2.

Después de `terraform apply`, genera tráfico y abre Explore:

```powershell
curl.exe (terraform -chdir=infrastructure/aws output -raw service_b_health_url)
```

- Traces: origen Tempo. Busca el servicio `service-b`.
- Logs: origen Loki. Consulta `{service_name="service-b"}`.
- Metrics: origen Prometheus o Mimir. Busca `app_orders_processed` o `app.orders.processed`.

X-Ray y CloudWatch siguen recibiendo la misma telemetría.

## Supuestos

- La cuenta tiene VPC predeterminada y una subred pública en `us-east-1`. El laboratorio no crea VPC, subred ni Internet Gateway.
- La AMI es la estándar x86_64 de Amazon Linux 2023 publicada en `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`. Trae AWS CLI y el agente de Systems Manager. Docker se instala en el arranque.
- La etiqueta ECR es mutable para poder repetir el push de `lab`.
- El disco de 8 GB alcanza para Amazon Linux 2023, las tres imágenes y una base pequeña. No instales paquetes de más.
- IMDSv2 exige token y el hop limit es 2 para que el collector, dentro de Docker, use el rol de la instancia.
- La IPv4 pública es la automática de la subred. Cambia si la instancia se detiene. No hay Elastic IP.
- Quien aplica necesita permisos para crear estos recursos. El pipeline de GitHub solo ejecuta `fmt`, `init -backend=false` y `validate`.
- `grafana_otlp_auth` es sensible. El ejemplo versionado usa un placeholder que el plan rechaza cuando `create_instance` es true.

## Integrador: RDS para data-service

`create_integrator_data` vale `false`. No cambies `create_instance`. Si lo devuelves a `false` mientras la EC2 exista, un apply la elimina. Lo mismo pasa con RDS si devuelves `create_integrator_data` a `false`.

Con el interruptor en `true`, Terraform crea en la VPC predeterminada:

- un Security Group que acepta TCP 5432 solo desde `gcp_egress_cidr`
- un DB subnet group con las subredes default de al menos dos zonas
- un parameter group `postgres16` con `rds.force_ssl=1`
- una instancia `otel-multicloud-lab-data`

No crea NAT Gateway, ni abre `0.0.0.0/0`, ni SSH. RDS es `db.t4g.micro`, PostgreSQL 16, una sola zona, 20 GB gp3 cifrados, sin Multi-AZ, sin réplicas, sin Enhanced Monitoring y sin Performance Insights. `backup_retention_period = 0`, `deletion_protection = false`, `skip_final_snapshot = true` y `apply_immediately = true`. `publicly_accessible = true` solo para que Cloud Run, saliendo por la IP de Cloud NAT, pueda llegar. La contraseña la administra RDS en Secrets Manager (`manage_master_user_password`). No está en tfvars ni en un output. El output sensible es el ARN del secreto.

La base y el usuario se llaman `otel_integrator` y `data_service`. Los tags `Project=otel-multicloud-lab`, `Environment=university-lab` y `Component=integrator-data` identifican estos recursos.

`gcp_egress_cidr` tiene que ser una IPv4 `/32` cuando el interruptor está en `true`. En `false` puede ser `null`. `0.0.0.0/0` no pasa la validación.

### Orden

Edita el tfvars existente. No lo sustituyas por el ejemplo y no pegues una IP real en Git.

1. En GCP, con `create_integrator_foundation = true` y `create_data_service = false`, aplica y copia `cloud_run_egress_cidr`.
2. En el tfvars de AWS:

```hcl
create_integrator_data = true
gcp_egress_cidr        = "203.0.113.10/32"
```

Sustituye el CIDR de documentación por el output. Después:

```powershell
terraform -chdir=infrastructure/aws plan
terraform -chdir=infrastructure/aws apply
```

3. Desde la raíz del repositorio Git, sin imprimir secretos:

```powershell
.\otel-multicloud-lab\scripts\provision-integrator-secrets.ps1 -GcpProjectId PROYECTO -AwsRegion us-east-1
```

El script lee el endpoint, el puerto, el nombre de la base y el ARN. Arma la URL con `ssl=require`, la carga como versión de `data-service-aws-database-url` y borra el archivo temporal. Respeta `AWS_CA_BUNDLE` y no desactiva TLS.

4. Publica la imagen de data-service y crea Cloud Run. Está en `infrastructure/gcp/README.md`.
5. Ejecuta el job de migración. Terraform no lo lanza.
6. Comprueba `/health` y `/ready` con un identity token.

### Destrucción, al revés

1. Apaga data-service y el job en GCP (`create_data_service` y `create_data_migration_job` en `false`) y aplica.
2. `create_integrator_data = false` y aplica AWS. RDS se borra sin snapshot final. No toques `create_instance`.
3. `create_integrator_foundation = false` y aplica GCP. Se van Cloud SQL, NAT, la IP y la red.
4. Confirma que no quedan la instancia RDS, snapshots, la IP estática ni los secretos `data-service-*`.

Los cuatro recursos de RDS llevan `Component=integrator-data` para distinguirlos de la EC2.
