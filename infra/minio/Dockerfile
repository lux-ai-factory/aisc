# MinIO server and client built from source. MinIO stopped publishing community images in late
# 2025 (quay.io/minio/* and minio/* are refused), so the stack builds its own from the last source
# releases. One image serves both the server (minio) and the bucket job (mc).
FROM golang:1.24-alpine AS build
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

FROM alpine:3.22
RUN apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/bin/minio
COPY --from=build /out/mc /usr/bin/mc
EXPOSE 9000 9001
ENTRYPOINT ["/usr/bin/minio"]
