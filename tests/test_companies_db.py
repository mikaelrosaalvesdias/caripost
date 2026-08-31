import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


_temp_dir = tempfile.TemporaryDirectory()
os.environ["ADULT_META_DB_PATH"] = os.path.join(_temp_dir.name, "companies-test.db")

from app import db  # noqa: E402
from app import db_companies as companies_db  # noqa: E402
from app import migrations as schema_migrations  # noqa: E402


db.init_db()
companies_db.init_companies_db()


class BrandKitPersistenceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        _temp_dir.cleanup()

    def create_company(self, name):
        return companies_db.company_create({"name": name, "socials": {}})

    def test_company_lifecycle_defaults_to_prospect_and_is_exposed_everywhere(self):
        company = self.create_company("Novo prospect")

        self.assertEqual(company["lifecycle_stage"], "prospect")
        self.assertIsNone(company["converted_at"])
        listed = next(item for item in companies_db.company_list() if item["id"] == company["id"])
        self.assertEqual(listed["lifecycle_stage"], "prospect")
        self.assertIsNone(listed["converted_at"])

    def test_company_lifecycle_validation_and_managed_conversion_are_idempotent(self):
        company = companies_db.company_create({
            "name": "Prospect preservado",
            "socials": {"instagram": "prospect-preservado"},
            "notes": "Histórico comercial",
        })
        with self.assertRaises(ValueError):
            companies_db.company_update(company["id"], {"lifecycle_stage": "cliente"})
        self.assertEqual(companies_db.company_get(company["id"])["lifecycle_stage"], "prospect")

        converted = companies_db.company_convert_to_managed(company["id"])
        repeated = companies_db.company_convert_to_managed(company["id"])

        self.assertEqual(converted["id"], company["id"])
        self.assertEqual(converted["name"], company["name"])
        self.assertEqual(converted["socials"], company["socials"])
        self.assertEqual(converted["notes"], company["notes"])
        self.assertEqual(converted["lifecycle_stage"], "managed")
        self.assertIsNotNone(converted["converted_at"])
        self.assertEqual(repeated["converted_at"], converted["converted_at"])
        self.assertEqual(repeated["updated_at"], converted["updated_at"])

    def test_legacy_company_rows_are_migrated_as_managed(self):
        with tempfile.TemporaryDirectory() as legacy_dir:
            legacy_path = Path(legacy_dir) / "legacy.db"
            with patch.object(db, "DB_PATH", legacy_path):
                with db.get_conn() as conn:
                    conn.execute("""
                        CREATE TABLE companies (
                            id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                            segment TEXT, city TEXT, state TEXT, website TEXT, phone TEXT, email TEXT,
                            socials TEXT NOT NULL DEFAULT '{}', notes TEXT,
                            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute(
                        "INSERT INTO companies (id, name, slug, socials, created_at, updated_at) "
                        "VALUES ('legacy-1', 'Cliente legado', 'cliente-legado', '{}', 'old', 'old')"
                    )
                companies_db.init_companies_db()

                legacy = companies_db.company_get("legacy-1")
                new_company = companies_db.company_create({"name": "Prospect pós-migração"})

                self.assertEqual(legacy["lifecycle_stage"], "managed")
                self.assertIsNone(legacy["converted_at"])
                self.assertEqual(new_company["lifecycle_stage"], "prospect")

    def test_atomic_brand_upsert_and_namespaced_extras(self):
        company = self.create_company("Persistência de marca")
        companies_db.brand_kit_upsert(company["id"], {
            "colors": {"primary": "#112233"},
            "voice": "manual",
            "audience": "provedores",
            "assuntos": "fibra",
            "creative_config": {"image": {"quality": "high"}},
            "source": "MANUAL",
        })
        companies_db.brand_kit_extras_patch(company["id"], {
            "palette_source": "manual",
            "manual_fields": ["voice"],
            "other_namespace": {"kept": True},
        })
        companies_db.brand_kit_extras_patch(company["id"], {
            "enrichment": {"state": "running", "run_id": "r1"},
        })

        kit = companies_db.brand_kit_get(company["id"])

        self.assertEqual(kit["colors"], {"primary": "#112233"})
        self.assertEqual(kit["audience"], "provedores")
        self.assertEqual(kit["assuntos"], "fibra")
        self.assertEqual(kit["creative_config"], {"image": {"quality": "high"}})
        self.assertTrue(kit["extras"]["other_namespace"]["kept"])
        self.assertEqual(kit["extras"]["enrichment"]["run_id"], "r1")

    def test_automatic_update_preserves_manual_values_until_explicit_replace(self):
        company = self.create_company("Curadoria concorrente")
        companies_db.brand_kit_upsert(company["id"], {
            "colors": {"primary": "#112233"}, "voice": "voz revisada",
        })
        companies_db.brand_kit_extras_patch(company["id"], {
            "palette_source": "manual", "manual_fields": ["voice"],
        })

        companies_db.brand_kit_apply_auto(company["id"], {
            "colors": {"primary": "#AABBCC"}, "voice": "voz automática",
        })
        preserved = companies_db.brand_kit_get(company["id"])
        self.assertEqual(preserved["colors"], {"primary": "#112233"})
        self.assertEqual(preserved["voice"], "voz revisada")

        companies_db.brand_kit_apply_auto(
            company["id"],
            {"colors": {"primary": "#AABBCC"}, "voice": "voz automática"},
            replace_manual_palette=True,
            replace_curated_fields=True,
        )
        replaced = companies_db.brand_kit_get(company["id"])
        self.assertEqual(replaced["colors"], {"primary": "#AABBCC"})
        self.assertEqual(replaced["voice"], "voz automática")
        self.assertEqual(replaced["extras"]["palette_source"], "automatic")

    def test_brand_colors_always_expose_one_canonical_primary(self):
        self.assertEqual(
            companies_db.normalize_brand_colors({"accent": "#abc", "branco": "ffffff"}),
            {"primary": "#AABBCC", "branco": "#FFFFFF"},
        )
        company = self.create_company("Contrato da paleta")
        companies_db.brand_kit_upsert(company["id"], {
            "colors": {"principal": "#123", "accentColor": "#456", "dourado": "#789abc"},
        })
        self.assertEqual(companies_db.brand_kit_get(company["id"])["colors"], {
            "primary": "#112233", "accent": "#445566", "dourado": "#789ABC",
        })

        # Simula uma linha legada gravada antes do contrato de cor principal.
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE brand_kits SET colors = ? WHERE company_id = ?",
                ('{"accent":"#0af","neutra":"#fff"}', company["id"]),
            )
        self.assertEqual(companies_db.brand_kit_get(company["id"])["colors"], {
            "primary": "#00AAFF", "neutra": "#FFFFFF",
        })

        self.assertEqual(
            companies_db.normalize_brand_colors({"primary": "azul", "verde": "#0f0"}),
            {"primary": "#00FF00"},
        )
        self.assertEqual(companies_db.normalize_brand_colors({"primary": "azul"}), {})

    def test_concurrent_primary_selection_leaves_one_logo_and_matching_brand_kit(self):
        company = self.create_company("Logos concorrentes")
        first = companies_db.asset_create(company["id"], {
            "kind": "IMAGE", "source": "UPLOADED", "url": "/uploads/first.png",
            "meta": {"role": "logo", "is_primary": False},
        })
        second = companies_db.asset_create(company["id"], {
            "kind": "IMAGE", "source": "UPLOADED", "url": "/uploads/second.png",
            "meta": {"role": "logo", "is_primary": False},
        })

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(
                lambda asset_id: companies_db.asset_set_primary_logo(
                    company["id"], asset_id, "MANUAL",
                ),
                (first["id"], second["id"]),
            ))

        logos = companies_db.asset_list_logos(company["id"])
        primary = [logo for logo in logos if (logo.get("meta") or {}).get("is_primary")]
        kit = companies_db.brand_kit_get(company["id"])
        self.assertEqual(len(primary), 1, logos)
        self.assertEqual(kit["logo_url"], primary[0]["url"])

    def test_auto_logo_cannot_replace_an_existing_manual_primary(self):
        company = self.create_company("Claim automático")
        manual = companies_db.asset_create(company["id"], {
            "kind": "IMAGE", "source": "UPLOADED", "url": "/uploads/manual.png",
            "meta": {"role": "logo", "is_primary": False},
        })
        automatic = companies_db.asset_create(company["id"], {
            "kind": "IMAGE", "source": "WEB", "url": "/uploads/automatic.png",
            "meta": {"role": "logo", "is_primary": False},
        })
        companies_db.asset_set_primary_logo(company["id"], manual["id"], "MANUAL")

        claimed = companies_db.asset_claim_primary_logo_if_empty(
            company["id"], automatic["id"], "AUTO",
        )

        self.assertFalse(claimed)
        kit = companies_db.brand_kit_get(company["id"])
        self.assertEqual(kit["logo_url"], manual["url"])

    def test_product_create_round_trips_briefing_fields(self):
        company = self.create_company("Produtos completos")
        product = companies_db.product_create(company["id"], {
            "name": "700 Mega",
            "description": "Internet por fibra com streaming.",
            "category": "Internet",
            "website": "https://example.com/700-mega",
            "socials": {"instagram": "@provedor"},
            "colors": {"primary": "#123456"},
            "objective": "Converter famílias que usam muitos dispositivos.",
            "functions": ["700 Mbps", "Wi-Fi incluso", "R$ 159,90/mês"],
            "knowledge": "Instalação grátis sujeita à viabilidade técnica.",
            "web_brief": "Oferta confirmada no site oficial.",
            "web_brief_at": "2026-08-07T12:00:00+00:00",
        })

        stored = companies_db.product_get(product["id"])

        self.assertEqual(stored["objective"], "Converter famílias que usam muitos dispositivos.")
        self.assertEqual(stored["functions"], ["700 Mbps", "Wi-Fi incluso", "R$ 159,90/mês"])
        self.assertEqual(stored["knowledge"], "Instalação grátis sujeita à viabilidade técnica.")
        self.assertEqual(stored["web_brief"], "Oferta confirmada no site oficial.")
        self.assertEqual(stored["web_brief_at"], "2026-08-07T12:00:00+00:00")

    def test_solution_round_trips_complete_profile_and_owns_its_assets(self):
        company = self.create_company("Catálogo de adicionais completo")
        other = self.create_company("Outro dono de adicionais")
        product = companies_db.product_create(company["id"], {"name": "Zapping"})
        solution = companies_db.solution_create(product["id"], {
            "name": "Telecine",
            "description": "Pacote com canais e catálogo Telecine.",
            "category": "Cinema",
            "website": "https://example.com/telecine",
            "socials": {"instagram": "@telecine"},
            "colors": {"primary": "#112233", "accent": "#FF9900"},
            "objective": "Vender entretenimento premium.",
            "functions": ["Filmes", "Canais ao vivo"],
            "knowledge": "Disponível como adicional do Zapping.",
            "web_brief": "Informações conferidas no site.",
            "web_brief_at": "2026-08-31T12:00:00+00:00",
            "links": ["https://example.com/assine"],
            "active": False,
        })

        self.assertEqual(solution["description"], "Pacote com canais e catálogo Telecine.")
        self.assertEqual(solution["socials"], {"instagram": "@telecine"})
        self.assertEqual(solution["colors"]["accent"], "#FF9900")
        self.assertEqual(solution["functions"], ["Filmes", "Canais ao vivo"])
        self.assertEqual(solution["links"], ["https://example.com/assine"])
        self.assertFalse(solution["active"])

        logo = companies_db.asset_create(company["id"], {
            "product_id": product["id"],
            "solution_id": solution["id"],
            "url": "/uploads/telecine-logo.png",
            "meta": {"role": "logo"},
        })
        photo = companies_db.asset_create(company["id"], {
            "solution_id": solution["id"],
            "url": "/uploads/telecine-photo.png",
            "meta": {"role": "photo"},
        })

        # A mídia do adicional nunca vaza para a marca da empresa nem para o produto pai.
        self.assertIsNone(logo["product_id"])
        self.assertEqual(companies_db.asset_list_logos(company["id"]), [])
        self.assertEqual(companies_db.asset_list_logos(company["id"], product["id"]), [])
        self.assertEqual(companies_db.asset_list_photos(company["id"], product["id"]), [])
        self.assertEqual(
            {asset["id"] for asset in companies_db.asset_list_solution_assets(
                company["id"], solution["id"],
            )},
            {logo["id"], photo["id"]},
        )
        with self.assertRaisesRegex(ValueError, "não pertence"):
            companies_db.asset_create(other["id"], {
                "solution_id": solution["id"],
                "url": "/uploads/wrong-owner.png",
                "meta": {"role": "logo"},
            })

        updated = companies_db.solution_update(solution["id"], {
            "active": True, "colors": {"primary": "#ABCDEF"}, "functions": ["Streaming"],
        })
        self.assertTrue(updated["active"])
        self.assertEqual(updated["colors"], {"primary": "#ABCDEF"})
        self.assertEqual(updated["functions"], ["Streaming"])
        self.assertTrue(companies_db.solution_delete(solution["id"]))
        self.assertIsNone(companies_db.asset_get(logo["id"]))
        self.assertIsNone(companies_db.asset_get(photo["id"]))

    def test_catalog_schema_is_available_after_companies_init(self):
        with db.get_conn() as conn:
            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            product_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(products)").fetchall()
            }
            plan_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(product_plans)").fetchall()
            }
            solution_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(solutions)").fetchall()
            }
            asset_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(company_assets)").fetchall()
            }

        self.assertTrue({
            "product_groups", "product_plans", "company_catalog_links",
        }.issubset(tables))
        self.assertIn("group_id", product_columns)
        self.assertTrue({"features", "sort_order"}.issubset(plan_columns))
        self.assertTrue({
            "description", "category", "website", "socials", "colors", "objective",
            "functions", "knowledge", "web_brief", "web_brief_at", "active",
        }.issubset(solution_columns))
        self.assertIn("solution_id", asset_columns)

    def test_catalog_hierarchy_validates_ownership_and_copy_maps_group(self):
        source = self.create_company("Catálogo origem hierarquia")
        target = self.create_company("Catálogo destino hierarquia")
        other = self.create_company("Catálogo terceiro hierarquia")
        streaming = companies_db.product_group_create(source["id"], {
            "name": "Streaming", "description": "Entretenimento", "active": True,
        })
        other_group = companies_db.product_group_create(other["id"], {"name": "Saúde"})

        product = companies_db.product_create(source["id"], {
            "name": "Zapping", "group_id": streaming["id"],
        })
        self.assertEqual(product["group_id"], streaming["id"])
        listed = next(row for row in companies_db.product_list(source["id"])
                      if row["id"] == product["id"])
        self.assertEqual(listed["group_id"], streaming["id"])

        with self.assertRaises(ValueError):
            companies_db.product_create(source["id"], {
                "name": "Produto inválido", "group_id": other_group["id"],
            })
        with self.assertRaises(ValueError):
            companies_db.product_update(product["id"], {"group_id": other_group["id"]})

        self.assertIsNone(companies_db.product_update(product["id"], {"group_id": None})["group_id"])
        companies_db.product_update(product["id"], {"group_id": streaming["id"]})
        plan = companies_db.product_plan_create(product["id"], {
            "name": "Full", "description": "Plano completo",
            "features": ["Canais ao vivo", "Replay"], "sort_order": 2,
        })
        self.assertEqual(plan["company_id"], source["id"])
        self.assertEqual(plan["features"], ["Canais ao vivo", "Replay"])
        self.assertEqual(plan["sort_order"], 2)
        updated_plan = companies_db.product_plan_update(plan["id"], {
            "features": ["Canais ao vivo"], "sort_order": 1, "active": False,
        })
        self.assertEqual(updated_plan["features"], ["Canais ao vivo"])
        self.assertEqual(updated_plan["sort_order"], 1)
        self.assertFalse(updated_plan["active"])

        copied = companies_db.product_copy(product["id"], target["id"])
        copied_group = companies_db.product_group_get(copied["group_id"])
        self.assertNotEqual(copied["group_id"], streaming["id"])
        self.assertEqual(copied_group["company_id"], target["id"])
        self.assertEqual(copied_group["name"], streaming["name"])

    def test_catalog_links_validate_ownership_and_block_referenced_deletes(self):
        source = self.create_company("Catálogo compartilhado")
        target = self.create_company("Cliente com catálogo")
        other = self.create_company("Outro catálogo")
        group = companies_db.product_group_create(source["id"], {"name": "Streaming"})
        product = companies_db.product_create(source["id"], {
            "name": "Zapping", "group_id": group["id"],
        })
        plan = companies_db.product_plan_create(product["id"], {
            "name": "Lite+", "features": ["TV ao vivo"],
        })
        solution = companies_db.solution_create(product["id"], {"name": "Telecine"})
        other_product = companies_db.product_create(other["id"], {"name": "e-Saúde"})
        other_plan = companies_db.product_plan_create(other_product["id"], {"name": "Clínica"})
        other_solution = companies_db.solution_create(other_product["id"], {"name": "Aya"})

        with self.assertRaises(ValueError):
            companies_db.catalog_link_create(target["id"], {
                "source_company_id": other["id"], "product_id": product["id"],
            })
        with self.assertRaises(ValueError):
            companies_db.catalog_link_create(target["id"], {
                "source_company_id": source["id"], "product_id": product["id"],
                "plan_id": other_plan["id"],
            })
        with self.assertRaises(ValueError):
            companies_db.catalog_link_create(target["id"], {
                "source_company_id": source["id"], "product_id": product["id"],
                "plan_id": plan["id"], "solution_ids": [other_solution["id"]],
            })

        link = companies_db.catalog_link_create(target["id"], {
            "source_company_id": source["id"], "product_id": product["id"],
            "plan_id": plan["id"], "solution_ids": [solution["id"], solution["id"]],
            "notes": "Oferta contratada", "active": True,
        })
        self.assertEqual(link["solution_ids"], [solution["id"]])
        self.assertTrue(link["active"])
        self.assertEqual(companies_db.catalog_link_list(target["id"])[0]["id"], link["id"])
        self.assertTrue(companies_db.catalog_link_references_product(product["id"]))
        self.assertTrue(companies_db.catalog_link_references_plan(plan["id"]))
        self.assertTrue(companies_db.catalog_link_references_solution(solution["id"]))
        self.assertFalse(companies_db.product_plan_delete(plan["id"]))
        self.assertFalse(companies_db.solution_delete(solution["id"]))
        self.assertFalse(companies_db.product_delete(product["id"]))
        self.assertFalse(companies_db.product_group_delete(group["id"]))
        with self.assertRaisesRegex(ValueError, "Catálogo vinculado"):
            companies_db.company_delete(source["id"])

        self.assertTrue(companies_db.catalog_link_delete(link["id"]))
        self.assertFalse(companies_db.catalog_link_references_product(product["id"]))
        self.assertFalse(companies_db.catalog_link_references_plan(plan["id"]))
        self.assertFalse(companies_db.catalog_link_references_solution(solution["id"]))
        self.assertTrue(companies_db.product_plan_delete(plan["id"]))
        self.assertTrue(companies_db.solution_delete(solution["id"]))
        self.assertTrue(companies_db.product_delete(product["id"]))
        self.assertTrue(companies_db.product_group_delete(group["id"]))

    def test_product_catalog_migrations_are_versioned_and_idempotent(self):
        with tempfile.TemporaryDirectory() as legacy_dir:
            legacy_path = Path(legacy_dir) / "catalog-legacy.db"
            with patch.object(db, "DB_PATH", legacy_path), patch.object(
                schema_migrations, "DB_PATH", legacy_path,
            ):
                with db.get_conn() as conn:
                    conn.execute(
                        "CREATE TABLE companies (id TEXT PRIMARY KEY, name TEXT NOT NULL)"
                    )
                    conn.execute(
                        "CREATE TABLE products (id TEXT PRIMARY KEY, company_id TEXT NOT NULL, "
                        "name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                    )
                    conn.execute("CREATE TABLE app_users (user_id TEXT PRIMARY KEY)")

                first = schema_migrations.run_migrations()
                second = schema_migrations.run_migrations()
                with db.get_conn() as conn:
                    versions = {
                        int(row[0]) for row in conn.execute(
                            "SELECT version FROM schema_migrations"
                        ).fetchall()
                    }
                    product_columns = {
                        str(row[1]) for row in conn.execute("PRAGMA table_info(products)").fetchall()
                    }
                    solution_columns = {
                        str(row[1]) for row in conn.execute("PRAGMA table_info(solutions)").fetchall()
                    }
                    asset_columns = {
                        str(row[1]) for row in conn.execute("PRAGMA table_info(company_assets)").fetchall()
                    }

                self.assertIn(6, first)
                self.assertIn(7, first)
                self.assertEqual(second, [])
                self.assertIn(6, versions)
                self.assertIn(7, versions)
                self.assertIn("group_id", product_columns)
                self.assertIn("knowledge", solution_columns)
                self.assertIn("solution_id", asset_columns)


if __name__ == "__main__":
    unittest.main()
