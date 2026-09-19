-- +goose Up
CREATE TABLE tenants (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    public_id  VARCHAR(40)     NOT NULL,
    name       VARCHAR(128)    NOT NULL,
    created_at DATETIME(3)     NOT NULL,
    updated_at DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_tenants_public (public_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE users (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    public_id     VARCHAR(40)     NOT NULL,
    tenant_id     BIGINT UNSIGNED NOT NULL,
    email         VARCHAR(255)    NOT NULL,
    display_name  VARCHAR(128)    NOT NULL,
    password_hash VARCHAR(255)    NOT NULL,
    role          VARCHAR(32)     NOT NULL,
    created_at    DATETIME(3)     NOT NULL,
    updated_at    DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_public (public_id),
    UNIQUE KEY uk_users_email (email),
    KEY idx_users_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE conversations (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    public_id     VARCHAR(40)     NOT NULL,
    tenant_id     BIGINT UNSIGNED NOT NULL,
    user_id       BIGINT UNSIGNED NOT NULL,
    title         VARCHAR(255)    NOT NULL,
    active_run_id BIGINT UNSIGNED NULL,
    deleted_at    DATETIME(3)     NULL,
    created_at    DATETIME(3)     NOT NULL,
    updated_at    DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_conv_public (public_id),
    KEY idx_conv_owner_updated (tenant_id, user_id, updated_at),
    KEY idx_conv_active_run (active_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE runs (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    public_id     VARCHAR(40)     NOT NULL,
    tenant_id     BIGINT UNSIGNED NOT NULL,
    user_id       BIGINT UNSIGNED NOT NULL,
    conversation_id BIGINT UNSIGNED NOT NULL,
    status        VARCHAR(24)     NOT NULL,
    error_message TEXT            NULL,
    last_event_at DATETIME(3)     NULL,
    created_at    DATETIME(3)     NOT NULL,
    updated_at    DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_runs_public (public_id),
    KEY idx_runs_owner (tenant_id, user_id, conversation_id),
    KEY idx_runs_status_time (status, last_event_at, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE messages (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    public_id       VARCHAR(40)     NOT NULL,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    user_id         BIGINT UNSIGNED NOT NULL,
    conversation_id BIGINT UNSIGNED NOT NULL,
    run_id          BIGINT UNSIGNED NULL,
    role            VARCHAR(16)     NOT NULL,
    content         MEDIUMTEXT      NOT NULL,
    created_at      DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_msg_public (public_id),
    UNIQUE KEY uk_msg_run_role (run_id, role),
    KEY idx_msg_conv (tenant_id, conversation_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE run_events (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    user_id         BIGINT UNSIGNED NOT NULL,
    run_id          BIGINT UNSIGNED NOT NULL,
    conversation_id BIGINT UNSIGNED NOT NULL,
    seq             BIGINT          NOT NULL,
    type            VARCHAR(64)     NOT NULL,
    payload         JSON            NOT NULL,
    created_at      DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_run_seq (run_id, seq),
    KEY idx_events_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- +goose Down
DROP TABLE IF EXISTS run_events;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS tenants;
