# syntax=docker/dockerfile:1.19
# RabbitMQ with the broker settings AISC adds.
FROM rabbitmq:3.13.7-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69
COPY --chmod=a=rX conf.d/10-aisc.conf /etc/rabbitmq/conf.d/10-aisc.conf
