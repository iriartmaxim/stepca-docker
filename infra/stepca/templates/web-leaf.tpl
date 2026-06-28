{
	"subject": {{ toJson .Subject }},
	"sans": {{ toJson .SANs }},
{{- if typeIs "string" .Insecure.User.profile }}
	{{- if eq .Insecure.User.profile "tls-client" }}
	"keyUsage": ["digitalSignature"],
	"extKeyUsage": ["clientAuth"],
	{{- else if eq .Insecure.User.profile "mtls" }}
	"keyUsage": ["digitalSignature", "keyEncipherment"],
	"extKeyUsage": ["serverAuth", "clientAuth"],
	{{- else if eq .Insecure.User.profile "code-signing" }}
	"keyUsage": ["digitalSignature"],
	"extKeyUsage": ["codeSigning"],
	{{- else if eq .Insecure.User.profile "email" }}
	"keyUsage": ["digitalSignature", "keyEncipherment"],
	"extKeyUsage": ["emailProtection"],
	{{- else }}
	"keyUsage": ["digitalSignature", "keyEncipherment"],
	"extKeyUsage": ["serverAuth"],
	{{- end }}
{{- else }}
	"keyUsage": ["digitalSignature", "keyEncipherment"],
	"extKeyUsage": ["serverAuth", "clientAuth"],
{{- end }}
	"basicConstraints": {"isCA": false}
}
