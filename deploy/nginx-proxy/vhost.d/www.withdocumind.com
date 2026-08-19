# Keep the ACME HTTP-01 challenge on the shared proxy. Redirect every other
# request to the canonical root hostname while preserving path and query.
if ($request_uri !~ "^/\\.well-known/acme-challenge/") {
    return 301 https://withdocumind.com$request_uri;
}
