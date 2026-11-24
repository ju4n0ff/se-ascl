-- SeñaCL · 002_drop_username (destructivo; snapshot antes)
-- Ejecutar solo después de desplegar el backend y el frontend que ya no usan `username`.
DROP INDEX IF EXISTS public.idx_users_username;

DO $migracion$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'username'
    ) THEN
        ALTER TABLE public.users DROP COLUMN username;
    END IF;
END
$migracion$;
