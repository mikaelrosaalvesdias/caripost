import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor


_temp_dir = tempfile.TemporaryDirectory()
os.environ["ADULT_META_DB_PATH"] = os.path.join(_temp_dir.name, "companies-test.db")

from app import db  # noqa: E402
from app import db_companies as companies_db  # noqa: E402


db.init_db()
companies_db.init_companies_db()


class BrandKitPersistenceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        _temp_dir.cleanup()

    def create_company(self, name):
        return companies_db.company_create({"name": name, "socials": {}})

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


if __name__ == "__main__":
    unittest.main()
