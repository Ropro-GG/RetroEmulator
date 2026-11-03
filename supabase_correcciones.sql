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
