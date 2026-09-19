package sse

import (
	"sync"

	"deepresearch/internal/mq"
)

const (
	MaxSubsPerRun   = 16
	MaxSubsPerInst  = 2000
	ChanBuf         = 64
)

type Hub struct {
	mu      sync.Mutex
	runs    map[string]map[chan mq.Event]struct{}
	convs   map[string]map[chan mq.Event]struct{}
	total   int
}

func New() *Hub {
	return &Hub{
		runs:  map[string]map[chan mq.Event]struct{}{},
		convs: map[string]map[chan mq.Event]struct{}{},
	}
}

func (h *Hub) Connections() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.total
}

func (h *Hub) SubscribeRun(runID string) (<-chan mq.Event, func(), bool) {
	return h.subscribe(h.runs, runID, MaxSubsPerRun)
}

func (h *Hub) SubscribeConv(convID string) (<-chan mq.Event, func(), bool) {
	return h.subscribe(h.convs, convID, MaxSubsPerRun)
}

func (h *Hub) subscribe(m map[string]map[chan mq.Event]struct{}, key string, perKey int) (<-chan mq.Event, func(), bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.total >= MaxSubsPerInst {
		return nil, nil, false
	}
	set := m[key]
	if set == nil {
		set = map[chan mq.Event]struct{}{}
		m[key] = set
	}
	if len(set) >= perKey {
		return nil, nil, false
	}
	ch := make(chan mq.Event, ChanBuf)
	set[ch] = struct{}{}
	h.total++
	return ch, func() {
		h.mu.Lock()
		defer h.mu.Unlock()
		if s := m[key]; s != nil {
			if _, ok := s[ch]; ok {
				delete(s, ch)
				h.total--
				close(ch)
			}
			if len(s) == 0 {
				delete(m, key)
			}
		}
	}, true
}

func (h *Hub) Publish(ev mq.Event) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for ch := range h.runs[ev.RunID] {
		select {
		case ch <- ev:
		default:
		}
	}
	if ev.Type == "run.started" {
		created := ev
		created.Type = "run.created"
		for ch := range h.convs[ev.ConversationID] {
			select {
			case ch <- created:
			default:
			}
		}
	}
}
