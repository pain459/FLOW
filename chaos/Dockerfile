FROM chaostoolkit/chaostoolkit:1.21.4@sha256:ff1427c09b029e82796e430d9bf6e127f992da247a27175d64eb1193149e86fe
USER root
COPY chaos/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock && mkdir /evidence /control && chown -R 1001:1001 /evidence /control
WORKDIR /workspace
ENV PYTHONPATH=/workspace PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --chown=1001:1001 chaos chaos
COPY --chown=1001:1001 shared shared
COPY --chown=1001:1001 verifier verifier
COPY --chown=1001:1001 load_generator/controller load_generator/controller
ENTRYPOINT ["python", "-m", "chaos.cli"]
USER 1001
CMD ["list"]
