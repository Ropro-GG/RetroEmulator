// aviso-llave: avisa por correo que se cambió la frase de una cuenta. Nunca recibe ni envía la frase.
// Solo atiende los avisos que dejó el trigger de la base, así que llamarla desde afuera no permite enviar nada a nadie.
import { createClient } from "npm:@supabase/supabase-js@2.45.4";
import nodemailer from "npm:nodemailer@6.9.16";

const TEXTO = `Hola:

Se creó una frase de recuperación nueva para tu cuenta de RetroEmulator.

Si fuiste vos, no tenés que hacer nada. Si no fuiste vos, cambiá tu contraseña ahora y respondé a este correo.

RetroEmulator nunca te va a pedir tu frase de recuperación.`;

Deno.serve(async () => {
  const usuario = Deno.env.get("AVISO_SMTP_USUARIO");
  const clave = Deno.env.get("AVISO_SMTP_CLAVE");
  if (!usuario || !clave) return new Response("Falta configurar el correo", { status: 503 });

  const base = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const correo = nodemailer.createTransport({ host: "smtp.gmail.com", port: 465, secure: true, auth: { user: usuario, pass: clave } });

  const { data: avisos, error } = await base.from("avisos_llave").select("id, usuario").is("enviado_en", null).limit(20);
  if (error) return new Response("No se pudieron leer los avisos", { status: 500 });

  let enviados = 0;
  for (const aviso of avisos ?? []) {
    try {
      const { data } = await base.auth.admin.getUserById(aviso.usuario);
      if (data.user?.email) {
        await correo.sendMail({ from: `RetroEmulator <${usuario}>`, to: data.user.email, subject: "Se cambió tu frase de recuperación", text: TEXTO });
        enviados++;
      }
      await base.from("avisos_llave").update({ enviado_en: new Date().toISOString() }).eq("id", aviso.id);
    } catch (e) {
      console.error("Aviso sin enviar:", aviso.id, String(e));   // queda pendiente para el próximo intento
    }
  }
  return Response.json({ enviados });
});
