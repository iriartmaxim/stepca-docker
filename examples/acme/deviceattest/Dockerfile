# Imagen de demo para device-attest-01: TPM por software (swtpm) + step CLI.
# Provee /dev/tpmrm0 vía CUSE y un EK con certificado de una CA local, de modo
# que step-ca pueda verificar la atestación TPM contra attestationRoots.
FROM smallstep/step-ca:0.28.3 AS stepsrc

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        swtpm swtpm-tools tpm2-tools libtpms0 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
# CLI step + plugin KMS (tpmkms)
COPY --from=stepsrc /usr/local/bin/step /usr/local/bin/step
COPY --from=stepsrc /usr/local/bin/step-kms-plugin /usr/local/bin/step-kms-plugin
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh
ENTRYPOINT ["/usr/local/bin/run.sh"]
