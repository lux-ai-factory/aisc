# MinIO server and client built from source. MinIO stopped publishing community images in late
# 2025 (quay.io/minio/* and minio/* are refused), so the stack builds its own from the last source
# releases. One image serves both the server (minio) and the bucket job (mc).
FROM golang:1.24.13-alpine@sha256:8bee1901f1e530bfb4a7850aa7a479d17ae3a18beb6e09064ed54cfd245b7191 AS build
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
RUN apk add --no-cache git
ENV CGO_ENABLED=0 GOTOOLCHAIN=auto
# the release stamped in as MinIO's own build does (buildscripts/gen-ldflags.go), so logs name it
RUN git clone --depth 1 --branch "$MINIO_RELEASE" https://github.com/minio/minio /src/minio \
 && cd /src/minio \
 && v=$(echo "$MINIO_RELEASE" | sed -E 's/^RELEASE\.([0-9-]+)T([0-9]+)-([0-9]+)-([0-9]+)Z$/\1T\2:\3:\4Z/') \
 && go build -trimpath -o /out/minio -ldflags "-s -w -X github.com/minio/minio/cmd.Version=$v \
      -X github.com/minio/minio/cmd.ReleaseTag=$MINIO_RELEASE -X github.com/minio/minio/cmd.CommitID=$(git rev-parse HEAD)" .
RUN git clone --depth 1 --branch "$MC_RELEASE" https://github.com/minio/mc /src/mc \
 && cd /src/mc && go build -trimpath -ldflags "-s -w" -o /out/mc .

FROM alpine:3.22.6@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
RUN apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/bin/minio
COPY --from=build /out/mc /usr/bin/mc
# starts the server and sets aside a stored config written by another MinIO version (see the script)
COPY entrypoint.sh /usr/local/bin/minio-entrypoint.sh
RUN chmod 755 /usr/local/bin/minio-entrypoint.sh
# its own user, with a home for mc's settings; an older volume made by root is handed over by the one-shot
# minio-data-owner before the server starts
RUN adduser -D -u 10030 -h /home/minio minio && mkdir -p /data && chown minio:minio /data
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio-entrypoint.sh"]
