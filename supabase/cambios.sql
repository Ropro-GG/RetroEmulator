-- Registro de cambios de la base desde el 2026-11-03. El esquema anterior solo existe en Supabase.
-- Cada bloque se puede ejecutar más de una vez.

-- supabase_correcciones.sql - Correcciones de la revisión del 2026-11-03.
-- Se puede ejecutar más de una vez. Todo corre en una sola transacción: si algo falla, no cambia nada.
begin;

-- 1. Invitaciones sin respuesta: quien no atendió (o no estaba conectado) ocupaba un lugar para
--    siempre y no se lo podía volver a invitar. Ahora vencen a los 60 s (LL_VIGENCIA_MS en llamadas.js).
create or replace function public.invitar_a_llamada(p_llamada uuid, p_usuarios uuid[])
returns void
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
    u uuid;
    ocupados int;
begin
    if not public.esta_unido_llamada(p_llamada) then
        raise exception 'No estas en esa llamada';
    end if;
    if (select estado from public.llamadas where id = p_llamada) = 'terminada' then
        raise exception 'La llamada ya termino';
    end if;

    select count(*) into ocupados from public.llamada_participantes
        where llamada_id = p_llamada
          and (estado = 'unido' or (estado = 'invitado' and invitado_en > now() - interval '60 seconds'));
    if ocupados + coalesce(array_length(p_usuarios, 1), 0) > 6 then
        raise exception 'Maximo 6 personas por llamada';
    end if;

    foreach u in array coalesce(p_usuarios, '{}'::uuid[]) loop
        -- Solo amigos aceptados; a uno mismo no
        if u = auth.uid() or not public.son_amigos(auth.uid(), u) then
            continue;
        end if;
        insert into public.llamada_participantes (llamada_id, usuario_id, estado, invitado_por, invitado_en)
        values (p_llamada, u, 'invitado', auth.uid(), now())
        on conflict (llamada_id, usuario_id) do update
            set estado = 'invitado', invitado_por = auth.uid(), invitado_en = now()
            where public.llamada_participantes.estado in ('salio', 'rechazado')
               or (public.llamada_participantes.estado = 'invitado'
                   and public.llamada_participantes.invitado_en <= now() - interval '60 seconds');
    end loop;
end;
$function$;

-- 2. Cualquier invitado podía cambiar todas las columnas de la llamada (también creador_id).
--    Se deja solo lo que la app actualiza, igual que ya se hace en friendships y mensajes.
revoke update on public.llamadas from anon, authenticated;
grant update (estado, inicio_en, terminada_en) on public.llamadas to authenticated;

-- 3. Cualquier usuario con sesión podía subir o reemplazar la foto de perfil de OTRO usuario.
drop policy if exists "Usuarios pueden subir avatares" on storage.objects;
drop policy if exists "Usuarios pueden actualizar avatares" on storage.objects;
create policy "Usuarios pueden subir avatares" on storage.objects
    for insert to authenticated
    with check (bucket_id = 'avatars' and name = 'avatar_' || auth.uid()::text || '.png');
create policy "Usuarios pueden actualizar avatares" on storage.objects
    for update to authenticated
    using (bucket_id = 'avatars' and name = 'avatar_' || auth.uid()::text || '.png')
    with check (bucket_id = 'avatars' and name = 'avatar_' || auth.uid()::text || '.png');

-- El bucket de avatares no tenía límite de tamaño (los otros dos tienen 5 MB).
update storage.buckets set file_size_limit = 5242880 where id = 'avatars';

-- 4. Funciones SECURITY DEFINER que se podían ejecutar sin iniciar sesión.
revoke execute on function public.es_participante_llamada(uuid) from public, anon;
revoke execute on function public.esta_unido_llamada(uuid) from public, anon;
revoke execute on function public.invitar_a_llamada(uuid, uuid[]) from public, anon;
revoke execute on function public.son_amigos(uuid, uuid) from public, anon;
grant execute on function public.es_participante_llamada(uuid) to authenticated;
grant execute on function public.esta_unido_llamada(uuid) to authenticated;
grant execute on function public.invitar_a_llamada(uuid, uuid[]) to authenticated;
grant execute on function public.son_amigos(uuid, uuid) to authenticated;
-- La usa solo el trigger de registro: nadie necesita llamarla directamente.
revoke execute on function public.handle_new_user() from public, anon, authenticated;

-- 5. search_path fijo (aviso del linter de Supabase).
alter function public.handle_new_user() set search_path = public;
alter function public.registrar_jugada set search_path = public;

commit;

-- supabase_fase5.sql - "En llamada" visible solo para amigos aceptados.
-- Tabla aparte de 'presencia': aquella se borra al cerrar el emulador y no debe llevarse esto.
create table if not exists public.presencia_llamada (
    user_id uuid primary key references auth.users(id) on delete cascade,
    desde timestamptz not null default now()
);

alter table public.presencia_llamada enable row level security;

revoke all on public.presencia_llamada from anon;
grant select, insert, update, delete on public.presencia_llamada to authenticated;

drop policy if exists presencia_llamada_select on public.presencia_llamada;
create policy presencia_llamada_select on public.presencia_llamada
    for select to authenticated
    using (user_id = (select auth.uid()) or public.son_amigos((select auth.uid()), user_id));

drop policy if exists presencia_llamada_insert on public.presencia_llamada;
create policy presencia_llamada_insert on public.presencia_llamada
    for insert to authenticated
    with check (user_id = (select auth.uid()));

drop policy if exists presencia_llamada_update on public.presencia_llamada;
create policy presencia_llamada_update on public.presencia_llamada
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists presencia_llamada_delete on public.presencia_llamada;
create policy presencia_llamada_delete on public.presencia_llamada
    for delete to authenticated
    using (user_id = (select auth.uid()));

-- ============================================================================
-- Bloquear y denunciar usuarios (2026-11-04)
-- ============================================================================
create table if not exists public.bloqueos (
    bloqueador uuid not null references auth.users(id) on delete cascade,
    bloqueado uuid not null references auth.users(id) on delete cascade,
    creado_en timestamptz not null default now(),
    primary key (bloqueador, bloqueado),
    check (bloqueador <> bloqueado)
);
create index if not exists bloqueos_bloqueado_idx on public.bloqueos (bloqueado);
alter table public.bloqueos enable row level security;
revoke all on public.bloqueos from anon, authenticated;
grant select, delete on public.bloqueos to authenticated;

-- Cada persona solo ve y quita sus propios bloqueos: nadie puede leer quién lo bloqueó.
drop policy if exists bloqueos_select on public.bloqueos;
create policy bloqueos_select on public.bloqueos for select to authenticated
    using (bloqueador = (select auth.uid()));
drop policy if exists bloqueos_delete on public.bloqueos;
create policy bloqueos_delete on public.bloqueos for delete to authenticated
    using (bloqueador = (select auth.uid()));

-- SECURITY DEFINER: las reglas deben ver también los bloqueos que hizo la otra persona.
create or replace function public.hay_bloqueo(p_a uuid, p_b uuid)
returns boolean language sql stable security definer set search_path to 'public' as $function$
    select exists (
        select 1 from public.bloqueos
        where (bloqueador = p_a and bloqueado = p_b) or (bloqueador = p_b and bloqueado = p_a)
    );
$function$;

-- Bloquea y borra la amistad en un solo paso. Sin amistad ya no hay chat, llamadas ni invitaciones.
create or replace function public.bloquear_usuario(p_usuario uuid)
returns void language plpgsql security definer set search_path to 'public' as $function$
begin
    if auth.uid() is null then raise exception 'Debes iniciar sesion'; end if;
    if p_usuario = auth.uid() then raise exception 'No podes bloquearte a vos mismo'; end if;
    insert into public.bloqueos (bloqueador, bloqueado) values (auth.uid(), p_usuario)
        on conflict do nothing;
    delete from public.friendships
        where (requester_id = auth.uid() and addressee_id = p_usuario)
           or (requester_id = p_usuario and addressee_id = auth.uid());
end;
$function$;

-- Usuarios que no deben aparecer en mis búsquedas, en cualquiera de los dos sentidos.
create or replace function public.ids_con_bloqueo()
returns setof uuid language sql stable security definer set search_path to 'public' as $function$
    select bloqueado from public.bloqueos where bloqueador = auth.uid()
    union
    select bloqueador from public.bloqueos where bloqueado = auth.uid();
$function$;

drop policy if exists friendships_insert on public.friendships;
create policy friendships_insert on public.friendships for insert to authenticated
    with check (auth.uid() = requester_id and status = 'pending'
                and not public.hay_bloqueo(requester_id, addressee_id));

drop policy if exists publicaciones_leer on public.publicaciones;
create policy publicaciones_leer on public.publicaciones for select to authenticated
    using (not public.hay_bloqueo((select auth.uid()), autor_id));

drop policy if exists comentarios_leer on public.publicaciones_comentarios;
create policy comentarios_leer on public.publicaciones_comentarios for select to authenticated
    using (not public.hay_bloqueo((select auth.uid()), autor_id));

-- SECURITY DEFINER: consultando publicaciones desde la regla, el bloqueo oculta justo esa
-- publicación, no se encuentra nada y el comentario se permitía.
create or replace function public.publicacion_con_bloqueo(p_publicacion bigint)
returns boolean language sql stable security definer set search_path to 'public' as $function$
    select exists (
        select 1 from public.publicaciones p
        where p.id = p_publicacion and public.hay_bloqueo(auth.uid(), p.autor_id)
    );
$function$;
revoke execute on function public.publicacion_con_bloqueo(bigint) from public, anon;
grant execute on function public.publicacion_con_bloqueo(bigint) to authenticated;

drop policy if exists comentarios_crear on public.publicaciones_comentarios;
create policy comentarios_crear on public.publicaciones_comentarios for insert to authenticated
    with check (auth.uid() = autor_id and not public.publicacion_con_bloqueo(publicacion_id));

-- Denuncias: se crean solo con denunciar_usuario y ningún usuario puede leerlas.
-- Se revisan en el panel de Supabase; si se borra una cuenta, la denuncia se conserva.
create table if not exists public.denuncias (
    id bigint generated always as identity primary key,
    denunciante uuid references auth.users(id) on delete set null,
    denunciado uuid references auth.users(id) on delete set null,
    motivo text not null check (motivo in ('acoso', 'spam', 'contenido', 'suplantacion', 'otro')),
    detalle text not null default '' check (char_length(detalle) <= 500),
    estado text not null default 'pendiente' check (estado in ('pendiente', 'leido', 'resuelto')),
    creada_en timestamptz not null default now()
);
create unique index if not exists denuncias_una_pendiente_idx
    on public.denuncias (denunciante, denunciado) where estado = 'pendiente';
alter table public.denuncias enable row level security;
revoke all on public.denuncias from anon, authenticated;

-- Devuelve false si ya había una denuncia pendiente de esa persona contra la misma persona.
create or replace function public.denunciar_usuario(p_usuario uuid, p_motivo text, p_detalle text default '')
returns boolean language plpgsql security definer set search_path to 'public' as $function$
declare
    filas int;
begin
    if auth.uid() is null then raise exception 'Debes iniciar sesion'; end if;
    if p_usuario = auth.uid() then raise exception 'No podes denunciarte a vos mismo'; end if;
    if (select count(*) from public.denuncias
         where denunciante = auth.uid() and creada_en > now() - interval '1 day') >= 20 then
        raise exception 'Demasiadas denuncias en un dia';
    end if;
    insert into public.denuncias (denunciante, denunciado, motivo, detalle)
        values (auth.uid(), p_usuario, p_motivo, coalesce(p_detalle, ''))
        on conflict (denunciante, denunciado) where estado = 'pendiente' do nothing;
    get diagnostics filas = row_count;
    return filas > 0;
end;
$function$;

revoke execute on function public.hay_bloqueo(uuid, uuid) from public, anon;
revoke execute on function public.bloquear_usuario(uuid) from public, anon;
revoke execute on function public.ids_con_bloqueo() from public, anon;
revoke execute on function public.denunciar_usuario(uuid, text, text) from public, anon;
grant execute on function public.hay_bloqueo(uuid, uuid) to authenticated;
grant execute on function public.bloquear_usuario(uuid) to authenticated;
grant execute on function public.ids_con_bloqueo() to authenticated;
grant execute on function public.denunciar_usuario(uuid, text, text) to authenticated;

-- Etapa 1 del cifrado: llave pública de cada cuenta. La privada nunca llega a la base.
alter table public.profiles add column if not exists llave_publica text
    check (llave_publica is null or llave_publica ~ '^[A-Za-z0-9+/]{43}=$');
