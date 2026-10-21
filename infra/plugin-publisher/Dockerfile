# The plugin publisher (compose service plugin-publisher): builds the bundled plugins and the plugin
# interface, and uploads them to the stack's devpi at bring-up. Its two tools come in the image,
# pinned, rather than from a pip install on every start.
FROM python:3.12-slim
RUN pip install --no-cache-dir build==1.6.1 twine==7.0.0
