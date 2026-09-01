#!/bin/sh
set -eu

mode=${1:-check}
case "$mode" in
    check|subscribe) ;;
    *) printf '%s\n' "usage: $0 [check|subscribe]" >&2; exit 64 ;;
esac

read_secret() {
    direct_name=$1
    file_name=$2
    eval "direct_value=\${$direct_name:-}"
    eval "secret_file=\${$file_name:-}"
    if [ -n "$direct_value" ] && [ -n "$secret_file" ]; then
        printf '%s\n' "configure only one of $direct_name or $file_name" >&2
        exit 78
    fi
    if [ -n "$direct_value" ]; then
        printf '%s' "$direct_value"
    elif [ -n "$secret_file" ] && [ -r "$secret_file" ]; then
        tr -d '\r\n' < "$secret_file"
    else
        printf '%s\n' "$direct_name is required" >&2
        exit 78
    fi
}

: "${META_GRAPH_VERSION:?META_GRAPH_VERSION is required}"
: "${META_WA_PHONE_NUMBER_ID:?META_WA_PHONE_NUMBER_ID is required}"
: "${META_WA_WABA_ID:?META_WA_WABA_ID is required}"

access_token=$(read_secret META_WA_ACCESS_TOKEN META_WA_ACCESS_TOKEN_FILE)
graph_base=${META_GRAPH_BASE_URL:-https://graph.facebook.com}
graph_base=${graph_base%/}/$META_GRAPH_VERSION
template=${META_DEFAULT_UTILITY_TEMPLATE:-bast_action_required_v1}
template_language=${META_TEMPLATE_LANGUAGE:-id}

printf '%s\n' "Checking Meta phone number and token..."
curl --fail --silent --show-error \
    --header "Authorization: Bearer $access_token" \
    "$graph_base/$META_WA_PHONE_NUMBER_ID?fields=display_phone_number,verified_name,quality_rating"
printf '\n%s\n' "Checking approved utility template..."
template_response=$(curl --fail --silent --show-error --get \
    --header "Authorization: Bearer $access_token" \
    --data-urlencode "name=$template" \
    --data-urlencode "fields=name,status,language,category" \
    "$graph_base/$META_WA_WABA_ID/message_templates")
printf '%s\n' "$template_response"
printf '%s' "$template_response" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"APPROVED"' || {
    printf '%s\n' "utility template is missing or not APPROVED: $template" >&2
    exit 78
}
printf '%s' "$template_response" | grep -Eq "\"language\"[[:space:]]*:[[:space:]]*\"$template_language\"" || {
    printf '%s\n' "approved template language is missing: $template_language" >&2
    exit 78
}

if [ "$mode" = "subscribe" ]; then
    printf '%s\n' "Subscribing the Meta app to the WABA..."
    curl --fail --silent --show-error --request POST \
        --header "Authorization: Bearer $access_token" \
        "$graph_base/$META_WA_WABA_ID/subscribed_apps"
    printf '\n'
fi

printf '%s\n' "Meta assets validated. Configure the App Dashboard callback to:"
printf '  %s/webhooks/whatsapp\n' "${META_WA_PUBLIC_BASE_URL:-https://REPLACE_WITH_PUBLIC_DOMAIN}"
