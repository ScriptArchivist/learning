{{- define "video-platform.name" -}}
video-platform
{{- end }}

{{- define "video-platform.fullname" -}}
{{ include "video-platform.name" . }}
{{- end }}