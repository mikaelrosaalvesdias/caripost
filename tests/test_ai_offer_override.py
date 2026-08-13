import json
import unittest
from unittest.mock import patch

from app import db_companies
from app.services import ai


class AiOfferOverrideTests(unittest.TestCase):
    def setUp(self):
        self.company = {
            "id": "target-1",
            "name": "Marca Prospect",
            "segment": "telecom",
            "brand_kit": {},
            "_offer_products_explicit": True,
            "_offer_products_override": [{
                "id": "offer-1",
                "name": "Produto CARIAP",
                "description": "Descrição verificada",
                "objective": "Gerar valor",
                "functions": ["Função real"],
                "knowledge": "Base factual",
                "web_brief": "Pesquisa validada",
            }],
        }

    def test_post_copy_uses_override_without_reading_target_catalog(self):
        response = json.dumps({
            "title": "Título", "headline": "Oferta forte", "subheadline": "Apoio",
            "benefits": ["Um", "Dois", "Três"], "cta": "Saiba mais", "copy": "Legenda",
            "hashtags": ["#teste"], "product": "Produto CARIAP", "media_type": "image",
            "visual_prompt": "Cena", "video_prompt": "",
        })
        with patch.object(ai, "get_ai_config", return_value={"provider": "x"}), \
             patch.object(ai, "cheap_text_config", return_value={"provider": "x"}), \
             patch.object(ai, "complete_ai", return_value=response) as complete, \
             patch.object(db_companies, "product_list", side_effect=AssertionError("catálogo-alvo não deve ser lido")):
            generated = ai.generate_post_copy(self.company, "Briefing", ["instagram"])

        self.assertEqual(generated["product"], "Produto CARIAP")
        prompt = complete.call_args.args[2]
        self.assertIn("Produto CARIAP", prompt)
        self.assertIn("catálogo de outra empresa", prompt)

    def test_video_context_uses_only_explicit_offer(self):
        with patch.object(db_companies, "product_list", side_effect=AssertionError("catálogo-alvo não deve ser lido")):
            context = ai._video_brief_context(self.company, "Vídeo do Produto CARIAP")

        self.assertIn("Produto CARIAP", context)
        self.assertIn("Base factual", context)

    def test_carousel_uses_external_offer_without_scanning_target_catalog(self):
        response = json.dumps({
            "theme": "Proposta",
            "slides": [
                {"type": "cover", "title": "Uma proposta forte", "app": ""},
                {"type": "content", "title": "Valor real", "body": "Benefício", "app": "Produto CARIAP"},
                {"type": "cta", "title": "Vamos conversar", "app": "Produto CARIAP"},
            ],
        })
        with patch.object(ai, "get_ai_config", return_value={"provider": "x"}), \
             patch.object(ai, "cheap_text_config", return_value={"provider": "x"}), \
             patch.object(ai, "complete_ai", return_value=response) as complete, \
             patch.object(db_companies, "product_list", side_effect=AssertionError("catálogo-alvo não deve ser lido")):
            result = ai.generate_carousel(
                self.company, "Produto CARIAP para o prospect", apps_focus=["Produto CARIAP"],
            )

        self.assertEqual(result["slides"][1]["app"], "Produto CARIAP")
        prompt = complete.call_args.args[2]
        self.assertIn("OFERTAS VINCULADAS A ESTE CONTEÚDO", prompt)
        self.assertIn("Base factual", prompt)

    def test_explicit_empty_offer_does_not_fall_back_to_target_products(self):
        company = {**self.company, "_offer_products_override": []}
        with patch.object(db_companies, "product_list", side_effect=AssertionError("fallback legado indevido")):
            self.assertEqual(ai._video_brief_context(company, "Institucional"), "")


if __name__ == "__main__":
    unittest.main()
