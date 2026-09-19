package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	SSEConnections = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "research_sse_connections",
		Help: "Open SSE connections on this instance",
	})
	EventsPersisted = promauto.NewCounter(prometheus.CounterOpts{
		Name: "research_events_persisted_total",
		Help: "Run events written by persist consumer",
	})
	RunsByStatus = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "research_run_status_total",
		Help: "Run status transitions observed",
	}, []string{"status"})
)
