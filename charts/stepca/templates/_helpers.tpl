{{- define "stepca.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "stepca.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "stepca.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "stepca.labels" -}}
app.kubernetes.io/name: {{ include "stepca.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "stepca.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{ .Values.secrets.existingSecret }}
{{- else -}}
{{ include "stepca.fullname" . }}-secrets
{{- end -}}
{{- end -}}
