package config

import (
	"strings"
	"time"

	"github.com/caarlos0/env/v11"

	"deepresearch/internal/upload"
)

type Config struct {
	HTTPAddr            string        `env:"HTTP_ADDR" envDefault:":8080"`
	MySQLDSN            string        `env:"MYSQL_DSN" envDefault:"research:research@tcp(127.0.0.1:3306)/research?charset=utf8mb4&parseTime=true&loc=UTC"`
	RedisAddr           string        `env:"REDIS_ADDR" envDefault:"127.0.0.1:6379"`
	KafkaBrokers        []string      `env:"KAFKA_BROKERS" envSeparator:"," envDefault:"127.0.0.1:9092"`
	CommandsTopic       string        `env:"KAFKA_COMMANDS_TOPIC" envDefault:"research.run.commands"`
	EventsTopic         string        `env:"KAFKA_EVENTS_TOPIC" envDefault:"research.run.events"`
	JWTSecret           string        `env:"JWT_SECRET" envDefault:"dev-change-me-please-use-32-bytes-min"`
	InstanceID          string        `env:"INSTANCE_ID" envDefault:"local-1"`
	CORSOrigins         []string      `env:"CORS_ORIGINS" envSeparator:"," envDefault:"http://localhost:5173"`
	AccessTTL           time.Duration `env:"ACCESS_TTL" envDefault:"15m"`
	RefreshTTL          time.Duration `env:"REFRESH_TTL" envDefault:"168h"`
	QueuedTimeout       time.Duration `env:"QUEUED_TIMEOUT_SEC" envDefault:"60s"`
	RunningStale        time.Duration `env:"RUNNING_STALE_SEC" envDefault:"120s"`
	JournalRetention    time.Duration `env:"JOURNAL_RETENTION_DAYS" envDefault:"168h"`
	RateLimitPerMinute  int           `env:"RATE_LIMIT_PER_MINUTE" envDefault:"120"`
	HistoryMessageLimit int           `env:"HISTORY_MESSAGE_LIMIT" envDefault:"40"`
	HistoryCharLimit    int           `env:"HISTORY_CHAR_LIMIT" envDefault:"80000"`
	UploadDir           string        `env:"UPLOAD_DIR" envDefault:"data/uploads"`
	UploadMaxBytes      int64         `env:"UPLOAD_MAX_BYTES" envDefault:"20971520"`
	UploadMaxFiles      int           `env:"UPLOAD_MAX_FILES" envDefault:"5"`
}

func Load() (Config, error) {
	var c Config
	if err := env.Parse(&c); err != nil {
		return c, err
	}
	if c.QueuedTimeout < time.Second {
		c.QueuedTimeout = time.Duration(c.QueuedTimeout) * time.Second
	}
	if c.RunningStale < time.Second {
		c.RunningStale = time.Duration(c.RunningStale) * time.Second
	}
	if c.JournalRetention < time.Hour {
		c.JournalRetention = c.JournalRetention * 24 * time.Hour
	}
	for i, o := range c.CORSOrigins {
		c.CORSOrigins[i] = strings.TrimSpace(o)
	}
	c.UploadDir = upload.ResolveDir(c.UploadDir)
	if c.UploadMaxBytes <= 0 {
		c.UploadMaxBytes = 20 << 20
	}
	if c.UploadMaxFiles <= 0 {
		c.UploadMaxFiles = 5
	}
	return c, nil
}
