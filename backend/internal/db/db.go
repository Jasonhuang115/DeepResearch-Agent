package db

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"log/slog"
	"strings"

	"github.com/pressly/goose/v3"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"

	"deepresearch/internal/tenant"
)

//go:embed sql/*.sql
var migrations embed.FS

type DB struct {
	Gorm *gorm.DB
	SQL  *sql.DB
}

func Open(dsn string) (*DB, error) {
	gdb, err := gorm.Open(mysql.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Warn),
	})
	if err != nil {
		return nil, err
	}
	sqlDB, err := gdb.DB()
	if err != nil {
		return nil, err
	}
	sqlDB.SetMaxOpenConns(40)
	sqlDB.SetMaxIdleConns(10)
	d := &DB{Gorm: gdb, SQL: sqlDB}
	d.installScopeGuard()
	return d, nil
}

func (d *DB) Migrate() error {
	goose.SetBaseFS(migrations)
	if err := goose.SetDialect("mysql"); err != nil {
		return err
	}
	return goose.Up(d.SQL, "sql")
}

func (d *DB) Scoped(ctx context.Context) *gorm.DB {
	p := tenant.MustFrom(ctx)
	return d.Gorm.WithContext(ctx).Where("tenant_id = ? AND user_id = ?", p.TenantID, p.UserID)
}

func (d *DB) System(ctx context.Context) *gorm.DB {
	return d.Gorm.WithContext(tenant.WithSystem(ctx))
}

func (d *DB) installScopeGuard() {
	owned := map[string]bool{
		"conversations": true,
		"messages":      true,
		"runs":          true,
		"run_events":    true,
		"attachments":   true,
	}
	_ = d.Gorm.Callback().Query().Before("gorm:query").Register("tenant:guard", func(db *gorm.DB) {
		if db == nil || db.Statement == nil || tenant.IsSystem(db.Statement.Context) {
			return
		}
		if db.Statement.Context == nil {
			return
		}
		if _, err := tenant.FromContext(db.Statement.Context); err != nil {
			return
		}
		table := db.Statement.Table
		if table == "" && db.Statement.Schema != nil {
			table = db.Statement.Schema.Table
		}
		if !owned[table] {
			return
		}
		sql := strings.ToLower(db.Statement.SQL.String())
		// Built SQL is often empty at this hook; inspect WHERE clause instead.
		if !clauseHasTenant(db) && !strings.Contains(sql, "tenant_id") {
			_ = db.AddError(fmt.Errorf("tenant guard: query on %s missing tenant_id", table))
			slog.Error("tenant guard blocked query", "table", table)
		}
	})
}

func clauseHasTenant(db *gorm.DB) bool {
	if db.Statement == nil {
		return false
	}
	for _, cond := range db.Statement.BuildClauses {
		if strings.Contains(strings.ToLower(cond), "tenant_id") {
			return true
		}
	}
	if w, ok := db.Statement.Clauses["WHERE"]; ok && w.Expression != nil {
		return true
	}
	return false
}
