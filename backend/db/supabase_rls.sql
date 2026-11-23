-- SeñaCL - Endurecimiento de Supabase (Row Level Security). Idempotente.
--
-- Supabase publica el esquema public por PostgREST y concede permisos a los roles anon y
-- authenticated. Sin RLS, cualquiera con la anon key podría leer users (hashes y emails).
-- Con RLS y sin políticas esos roles no ven ninguna fila. El backend se conecta como
-- postgres (dueño de las tablas), al que RLS no restringe.
--
-- Ejecutar después de schema.sql, y de nuevo cada vez que se recreen las tablas:
--   psql "<URL del pooler>" -1 -v ON_ERROR_STOP=1 -f db/supabase_rls.sql
-- o pegar en Supabase > SQL Editor. En PostgreSQL local es inocuo (los roles no existen).

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.history ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    rol TEXT;
    tabla TEXT;
BEGIN
    FOREACH rol IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = rol) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.users, public.history FROM %I', rol);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', rol);
            -- Tablas, secuencias y funciones futuras creadas por este mismo rol.
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', rol);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', rol);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM %I', rol);
        END IF;
    END LOOP;

    -- Avisa si quedó alguna otra tabla de public sin RLS.
    FOR tabla IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
    LOOP
        RAISE WARNING 'Tabla sin RLS en public: %', tabla;
    END LOOP;
END
$$;

-- Verificación: ambas filas deben mostrar rls = true.
SELECT relname AS tabla, relrowsecurity AS rls
FROM pg_class
WHERE oid IN ('public.users'::regclass, 'public.history'::regclass)
ORDER BY relname;
