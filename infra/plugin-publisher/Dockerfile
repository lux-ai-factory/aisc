# The plugin publisher (compose service plugin-publisher): a small internal HTTP service on port
# 8000 that fetches one plugin repo when the platform asks, builds it and uploads it to the stack's
# devpi; at its own start it publishes the plugin interface. The HTTP side is the standard library
# alone; git, build and twine come in the image, pinned, rather than from an install on every start.
FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir build==1.6.1 twine==7.0.0 \
    && useradd --system --create-home --shell /usr/sbin/nologin builder \
    # local_plugins/ is mounted under this: only root, the service, enters it; the builds (as builder) never read it
    && install -d -m 700 /srv/private
# A plugin's build runs that repo's own code (build backend, setup.py, build requirements), so it
# runs as builder through setpriv: with no secret in its environment, unable to read the service's
# in /proc/1, and unable to change /app. The service itself stays root to hand folders over and
# switch user; the upload, which needs devpi's password, stays with it.
ENV BUILD_AS_USER=builder
WORKDIR /app
COPY plugin_publisher ./plugin_publisher
EXPOSE 8000
CMD ["python", "-m", "plugin_publisher"]
