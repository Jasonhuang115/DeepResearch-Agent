package blob

import (
	"testing"

	"deepresearch/internal/config"
)

func TestOpenWithoutOSSUsesLocal(t *testing.T) {
	store := Open(config.Config{DurableRoot: t.TempDir()})
	if _, ok := store.(*Local); !ok {
		t.Fatalf("%T", store)
	}
}

func TestOpenWithOSSUsesOSS(t *testing.T) {
	store := Open(config.Config{
		DurableRoot:        t.TempDir(),
		OSSAccessKeyID:     "ak",
		OSSAccessKeySecret: "sk",
		OSSBucket:          "bucket",
		OSSEndpoint:        "oss-cn-beijing.aliyuncs.com",
	})
	if _, ok := store.(*OSS); !ok {
		t.Fatalf("%T", store)
	}
}
