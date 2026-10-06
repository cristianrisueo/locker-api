#!/usr/bin/env bash
# Dominio propio para la API desplegada (fase F7b, docs/especificaciones.md §13.5): api.lockerapi.dev -> locker-api.
# Usa el «domain mapping» de Cloud Run (en preview): Google emite y renueva el certificado HTTPS. El dominio y su DNS
# viven en Vercel, no en Google Cloud: este script no toca el DNS, solo imprime los registros que hay que añadir.
#
# Es idempotente: comprueba cada cosa antes de crearla, así que se puede repetir. Nunca cambia el servicio.
# Uso: deploy/domain.sh

# -e: para en el primer error; -u: una variable sin definir es un error; -o pipefail: falla la tubería si falla
# cualquiera de sus comandos, no solo el último
set -euo pipefail

# --- Configuración: los mismos nombres que setup.sh y teardown.sh ---

PROJECT_ID="locker-api-cristian"
PROJECT_NUMBER="953827667605"
REGION="europe-west1"
GCLOUD_CONFIG="locker-api"
API_SERVICE="locker-api"

# El dominio base (lo que se verifica como propio) y el subdominio de la API. La raíz queda libre para un frontend
BASE_DOMAIN="lockerapi.dev"
API_DOMAIN="api.lockerapi.dev"

# Espera del certificado: como mucho 30 minutos, comprobando cada 30 segundos
WAIT_CHECKS=60
WAIT_SECONDS=30

# --- Ayudantes ---

step() { printf '\n==> %s\n' "$1"; }
warn() { printf 'AVISO: %s\n' "$1" >&2; }
die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

# Comprueba que gcloud apunta a donde debe antes de tocar nada: la configuración activa, su proyecto y el número del
# proyecto (como setup.sh y teardown.sh)
check_target() {
  local active configured number
  active=$(gcloud config configurations list --filter=is_active=true --format='value(name)')
  [[ $active == "$GCLOUD_CONFIG" ]] || die "la configuración activa de gcloud es «${active}», no «${GCLOUD_CONFIG}»"
  configured=$(gcloud config get-value project 2>/dev/null)
  [[ $configured == "$PROJECT_ID" ]] || die "la configuración «${GCLOUD_CONFIG}» apunta a «${configured}», no a «${PROJECT_ID}»"
  number=$(gcloud projects describe "$PROJECT_ID" --project="$PROJECT_ID" --format='value(projectNumber)')
  [[ $number == "$PROJECT_NUMBER" ]] || die "el proyecto ${PROJECT_ID} tiene el número «${number}», no ${PROJECT_NUMBER}"
}

# Estado de una condición del mapeo (Ready, CertificateProvisioned, DomainRoutable): True, False, Unknown o vacío.
# describe no admite --filter: se saca una línea «tipo estado» por condición y awk se queda con la pedida
condition() {
  gcloud beta run domain-mappings describe --domain="$API_DOMAIN" --project="$PROJECT_ID" --region="$REGION" \
    --flatten='status.conditions' --format='value(status.conditions.type,status.conditions.status)' 2>/dev/null |
    awk -v type="$1" '$1 == type { print $2 }' || true
}

# Código HTTP de /health por el dominio propio (000 si todavía no conecta: DNS sin propagar o sin certificado)
health_code() {
  curl --silent --output /dev/null --write-out '%{http_code}' --max-time 10 "https://${API_DOMAIN}/health" || true
}

# --- 1. Comprobaciones previas ---

step "Comprobando la configuración de gcloud y el proyecto"
check_target
printf '    configuración %s, proyecto %s (%s), región %s\n' "$GCLOUD_CONFIG" "$PROJECT_ID" "$PROJECT_NUMBER" "$REGION"

# El mapeo de dominios está en la pista beta de gcloud (gcloud components install beta)
gcloud beta run domain-mappings --help >/dev/null 2>&1 ||
  die "falta el componente beta de gcloud: instálalo con «gcloud components install beta»"

# El servicio tiene que existir (lo crea el CD). Solo se consulta: este script nunca lo cambia
gcloud run services describe "$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1 ||
  die "no existe el servicio ${API_SERVICE}: despliégalo antes con el CD"

# --- 2. Dominio verificado ---

# Google solo deja mapear un dominio que la cuenta haya demostrado que es suyo (un registro TXT en su DNS). La
# verificación se hace en el navegador (Search Console), así que el script no la hace: si falta, para y lo explica
step "Comprobando que ${BASE_DOMAIN} está verificado para esta cuenta"
verified=$(gcloud domains list-user-verified --project="$PROJECT_ID" --format='value(id)')
grep -qx "$BASE_DOMAIN" <<<"$verified" ||
  die "${BASE_DOMAIN} no está verificado. Ejecuta «gcloud domains verify ${BASE_DOMAIN}», añade en Vercel el TXT que te da Search Console y pulsa «Verificar» (README, «Dominio propio»)"
printf '    %s está verificado\n' "$BASE_DOMAIN"

# --- 3. Mapeo del dominio ---

step "Mapeo ${API_DOMAIN} -> servicio ${API_SERVICE}"
if gcloud beta run domain-mappings describe --domain="$API_DOMAIN" --project="$PROJECT_ID" --region="$REGION" \
  >/dev/null 2>&1; then
  printf '    ya existe\n'
else
  gcloud beta run domain-mappings create --service="$API_SERVICE" --domain="$API_DOMAIN" \
    --project="$PROJECT_ID" --region="$REGION"
fi

# --- 4. Registros DNS que pide Google ---

# Para un subdominio es un CNAME de «api» a ghs.googlehosted.com. Se ponen a mano en Vercel (README, «Dominio propio»)
step "Registros DNS que hay que tener en ${BASE_DOMAIN} (en Vercel)"
gcloud beta run domain-mappings describe --domain="$API_DOMAIN" --project="$PROJECT_ID" --region="$REGION" \
  --flatten='status.resourceRecords' \
  --format='table(status.resourceRecords.name:label=NAME,status.resourceRecords.type:label=TYPE,status.resourceRecords.rrdata:label=VALUE)'

# --- 5. Espera al certificado y a /health ---

# Con el CNAME en su sitio, Google comprueba el dominio y emite el certificado: suele tardar de 15 minutos a una hora.
# Se da por listo cuando https://api.lockerapi.dev/health responde 200, que exige DNS, certificado y servicio a la vez.
# Si se agota la espera no es un error: el certificado puede seguir llegando, y basta con volver a ejecutar el script
step "Esperando el certificado y /health (como mucho $((WAIT_CHECKS * WAIT_SECONDS / 60)) minutos)"
for check in $(seq 1 "$WAIT_CHECKS"); do
  code=$(health_code)
  if [[ $code == "200" ]]; then
    printf '    https://%s/health responde 200: listo\n' "$API_DOMAIN"
    exit 0
  fi
  printf '    %02d/%d: Ready=%s, certificado=%s, /health=%s; se espera %d s\n' "$check" "$WAIT_CHECKS" \
    "$(condition Ready)" "$(condition CertificateProvisioned)" "$code" "$WAIT_SECONDS"
  sleep "$WAIT_SECONDS"
done

warn "el certificado todavía no está listo tras $((WAIT_CHECKS * WAIT_SECONDS / 60)) minutos. Estado actual:"
gcloud beta run domain-mappings describe --domain="$API_DOMAIN" --project="$PROJECT_ID" --region="$REGION" \
  --flatten='status.conditions' \
  --format='table(status.conditions.type:label=CONDICIÓN,status.conditions.status:label=ESTADO,status.conditions.message:label=MENSAJE)'
warn "comprueba que el CNAME es visible (dig +short CNAME ${API_DOMAIN}) y vuelve a ejecutar el script más tarde"
