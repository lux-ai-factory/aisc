# Runbook: encrypt the files MinIO stored before encryption was on

MinIO encrypts every file it stores (SSE-S3) with the key in `env.secrets` `MINIO_KMS_SECRET_KEY`: `make_buckets`
turns it on for the engine's buckets (datasets, artifacts, models) and the proof buckets on every start, and the
platform on each proof bucket it makes. That applies to new files only. Files stored before the key existed stay
unencrypted, readable as before, until they are copied onto themselves.

This rewrites every stored file. It is an operator action: run it only with the owner's yes, after a backup
(`docs/runbooks/restore-a-backup.md`), with no run in flight.

1. Check the disk (`df -h /`) and take a backup of MinIO.
2. Keep `MINIO_KMS_SECRET_KEY` safe outside the checkout too: without it no encrypted file can be read again.
3. Copy each bucket onto itself as MinIO's root account, from inside the `minio` container (no password on a
   command line: `mc` reads the account from `MC_HOST_minio`, set in the container's environment):

   ```bash
   docker exec <prefix>minio sh -c 'export MC_HOST_minio="http://$MINIO_ROOT_USER:$MINIO_ROOT_PASSWORD@127.0.0.1:9000";
     for b in $(mc ls minio | awk "{print \$NF}" | tr -d /); do mc cp --recursive --preserve "minio/$b/" "minio/$b/"; done'
   ```

4. Check one file of each bucket: `mc stat minio/<bucket>/<file>` shows `Encryption: SSE-S3`.
