import time
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from prazos import auth


class TestAuth(unittest.TestCase):
    def test_scrypt_com_sal_independente(self):
        senha = "uma senha de teste"
        primeiro = auth.gerar_hash(senha)
        self.assertTrue(auth.conferir_senha(senha, primeiro))
        self.assertFalse(auth.conferir_senha("errada", primeiro))
        self.assertFalse(auth.conferir_senha(senha, "hash-invalido"))
        self.assertFalse(auth.conferir_senha(senha, None))
        self.assertNotEqual(primeiro, auth.gerar_hash(senha))

    def test_quinta_falha_bloqueia_por_quinze_minutos(self):
        agora = datetime.now(timezone.utc)
        registro = {"falhas": [agora - timedelta(seconds=i) for i in range(1, 5)],
                    "bloqueado_ate": None}
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [registro, {"agora": agora}]
        with patch.object(auth.db, "conectar", return_value=nullcontext(conn)), \
             patch.object(auth.db, "buscar_usuario_por_email", return_value=None), \
             patch.object(auth.time, "sleep") as esperar:
            with self.assertRaises(auth.LoginNegado) as erro:
                auth.entrar_com_senha("Usuario@example.com", "errada")
        self.assertTrue(erro.exception.bloqueado)
        falhas, bloqueado_ate, email = conn.execute.call_args.args[1]
        self.assertEqual(len(falhas), 5)
        self.assertEqual(bloqueado_ate, agora + timedelta(minutes=15))
        self.assertEqual(email, "usuario@example.com")
        esperar.assert_called_once_with(1)

    def test_google_rejeita_claims_invalidas(self):
        for campo, valor in (
            ("aud", "outro-client"), ("email_verified", False), ("hd", "outro.example"),
            ("iss", "https://outro.example"), ("exp", 0),
        ):
            with self.subTest(campo=campo), \
                 patch.object(auth, "google_client_id", return_value="painel-client"), \
                 patch.object(auth, "_verificar_google", return_value={**self.claims(), campo: valor}), \
                 patch.object(auth.db, "conectar") as conectar:
                with self.assertRaises(auth.LoginNegado):
                    auth.entrar_com_google("credential")
                conectar.assert_not_called()

    def test_google_rejeita_conta_nao_cadastrada(self):
        with patch.object(auth, "google_client_id", return_value="painel-client"), \
             patch.object(auth, "_verificar_google", return_value=self.claims()), \
             patch.object(auth.db, "conectar", return_value=nullcontext(object())), \
             patch.object(auth.db, "buscar_usuario_por_email", return_value=None):
            with self.assertRaises(auth.LoginNegado):
                auth.entrar_com_google("credential")

    @staticmethod
    def claims():
        return {
            "aud": "painel-client",
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "email": "usuario@pge.pr.gov.br",
            "hd": "pge.pr.gov.br",
            "exp": time.time() + 3600,
        }
