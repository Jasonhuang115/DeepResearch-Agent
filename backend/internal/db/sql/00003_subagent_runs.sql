-- +goose Up
ALTER TABLE runs
    ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'main' AFTER conversation_id,
    ADD COLUMN subagent_id VARCHAR(64) NULL AFTER kind,
    ADD COLUMN parent_run_id BIGINT UNSIGNED NULL AFTER subagent_id,
    ADD COLUMN parent_subagent_id VARCHAR(64) NULL AFTER parent_run_id,
    ADD COLUMN description VARCHAR(512) NULL AFTER parent_subagent_id,
    ADD COLUMN depth INT NOT NULL DEFAULT 0 AFTER description,
    ADD UNIQUE KEY uk_runs_conv_subagent (conversation_id, subagent_id);

-- +goose Down
ALTER TABLE runs
    DROP INDEX uk_runs_conv_subagent,
    DROP COLUMN depth,
    DROP COLUMN description,
    DROP COLUMN parent_subagent_id,
    DROP COLUMN parent_run_id,
    DROP COLUMN subagent_id,
    DROP COLUMN kind;
