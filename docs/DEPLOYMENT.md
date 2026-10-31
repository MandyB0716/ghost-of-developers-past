# Render deployment

The local app uses the existing Google Cloud CLI login. Render uses a separate
service-account credential, held in Render settings. Credentials and private
test outputs must not be committed to the repository.

## Web service settings

| Setting | Value |
| --- | --- |
| Source | `MandyB0716/ghost-of-developers-past` |
| Language | Python 3 |
| Branch | `main` |
| Root directory | Leave empty |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn --config gunicorn.conf.py app:app` |
| Health check path | `/healthz` |

The `.python-version` file selects Python 3.11 and Render's latest corresponding
patch version. Gunicorn uses one worker with four request threads, because
workspaces and version history live in that worker's memory. Use one Render
instance. Workspaces expire after an hour and are lost on restart or redeploy;
download a Markdown or PDF plan to keep it. The health check makes no model or
voice request; provider connectivity needs a separate live test.

## Environment variables

| Key | Value |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT` | `high-sunlight-512802-k0` |
| `ENABLE_GROK_BACKUP` | `true` |
| `SECRET_KEY` | Use Render's Generate button; at least 32 characters |
| `ELEVENLABS_API_KEY` | The existing project key, entered privately |
| `ELEVENLABS_VOICE_ID` | `EXAVITQu4vr4xnSDxMaL` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Complete JSON for the dedicated model-caller account, entered privately |

Do not set `PORT` or `RENDER_EXTERNAL_HOSTNAME`; Render supplies them. Do not
copy personal Google CLI credential databases or access tokens into Render.

As an alternative to `GOOGLE_SERVICE_ACCOUNT_JSON`, upload the dedicated JSON
as a Render secret file named `gcp-service-account.json` and set
`GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/gcp-service-account.json`.
Choose one credential method, not both. Standard Google ADC also supports
federated credentials through that file path if the hosting setup provides them.

## Dedicated Google identity

The intended account is
`revival-render@high-sunlight-512802-k0.iam.gserviceaccount.com`.
The proposed custom role in `deploy/google-model-caller-role.yaml` allows only
model prediction and consuming project APIs. It does not grant deployment,
training, IAM management, storage access, or permission to enable new models.
Creating this identity, binding its role, and creating a private key are cloud
access changes that must be approved before execution. Save the key outside the
project folder, then provide it only to Render's environment or secret-file
settings. Remove the key and its IAM binding when the hosted demo is retired.

Render's managed OIDC authentication currently requires a Pro workspace or
higher. This deployment does not require that upgrade. Service-account keys
are long-lived credentials; anyone who obtains one can use its permissions.

## Before and after deployment

1. Verify the repository contains code, examples, tests, documentation, and
   artwork, with `.env`, `.venv`, keys, and private test outputs excluded.
2. Run the automated checks and inspect the GitHub Actions Linux result,
   including Gunicorn configuration validation.
3. Set the web service settings and all required environment variables.
4. Deploy and confirm `/healthz` returns `{"status":"ok"}`.
5. Use the fictional example to verify a real analysis, source navigation,
   follow-up answers, both download formats, and ElevenLabs voice over HTTPS.
6. Record the public URL, a short demo, and the limits of this initial release
   in the submission. Do not describe a health check as proof that Google or
   ElevenLabs authentication works.

The public demo allows at most 40 analysis operations and 30 voice operations
per server process. Model retries are included inside an analysis operation.
Those counters reset on restart; they are not persistent billing limits.
