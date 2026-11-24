-- SeñaCL · 001_registro_email_perfil (aditivo, idempotente)
-- Ejecutar en Supabase > SQL Editor antes de desplegar el backend nuevo.
-- `apellido` queda nullable para cuentas legacy (decisión de backfill).
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS nombre VARCHAR(50),
    ADD COLUMN IF NOT EXISTS apellido VARCHAR(50),
    ADD COLUMN IF NOT EXISTS necesidad_accesibilidad VARCHAR(120),
    ADD COLUMN IF NOT EXISTS consentimiento_mejora BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS consentimiento_mejora_version VARCHAR(20),
    ADD COLUMN IF NOT EXISTS consentimiento_mejora_fecha TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS terminos_version VARCHAR(20),
    ADD COLUMN IF NOT EXISTS terminos_aceptados_en TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS privacidad_version VARCHAR(20),
    ADD COLUMN IF NOT EXISTS privacidad_aceptada_en TIMESTAMPTZ;

ALTER TABLE public.users DROP CONSTRAINT IF EXISTS ck_users_necesidad_accesibilidad;
ALTER TABLE public.users ADD CONSTRAINT ck_users_necesidad_accesibilidad CHECK (
    necesidad_accesibilidad IS NULL
    OR necesidad_accesibilidad ~ '^(auditiva|visual|motora|cognitiva_habla)(,(auditiva|visual|motora|cognitiva_habla)){0,3}$'
);

DO $migracion$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'username'
    ) THEN
        EXECUTE $backfill$
            UPDATE public.users
            SET
                nombre = COALESCE(nombre, NULLIF(split_part(replace(username, '_', ' '), ' ', 1), '')),
                terminos_version = COALESCE(terminos_version, 'legacy'),
                terminos_aceptados_en = COALESCE(terminos_aceptados_en, created_at),
                privacidad_version = COALESCE(privacidad_version, 'legacy'),
                privacidad_aceptada_en = COALESCE(privacidad_aceptada_en, created_at)
            WHERE username IS NOT NULL
        $backfill$;
    END IF;
END
$migracion$;

UPDATE public.users
SET nombre = 'Usuario ' || id
WHERE nombre IS NULL OR btrim(nombre) = '';

ALTER TABLE public.users ALTER COLUMN nombre SET NOT NULL;
