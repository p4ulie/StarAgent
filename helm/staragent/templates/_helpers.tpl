{{- define "staragent.labels" -}}
app.kubernetes.io/name: staragent
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "staragent.image" -}}
{{ .Values.image.registry }}/{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/* The environment every StarAgent process gets: config, Chroma's address and the Secret. */}}
{{- define "staragent.env" -}}
env:
  {{- range $k, $v := .Values.config }}
  - name: {{ $k }}
    value: {{ $v | quote }}
  {{- end }}
  - name: CHROMA_HOST
    value: {{ .Release.Name }}-chroma
  - name: CHROMA_PORT
    value: "8000"
  - name: MCP_PORT
    value: {{ .Values.mcp.port | quote }}
envFrom:
  - secretRef: {name: {{ .Values.existingSecret }}}
{{- end }}
