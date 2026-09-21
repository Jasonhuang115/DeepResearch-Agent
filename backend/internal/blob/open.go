package blob

import (
	"strings"

	"deepresearch/internal/config"
)

func Open(cfg config.Config) Store {
	if strings.TrimSpace(cfg.OSSAccessKeyID) != "" && strings.TrimSpace(cfg.OSSBucket) != "" &&
		strings.TrimSpace(cfg.OSSAccessKeySecret) != "" && strings.TrimSpace(cfg.OSSEndpoint) != "" {
		return NewOSS(cfg)
	}
	return NewLocal(cfg.DurableRoot)
}
