#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Small authored packaging fixtures; no game assets, compiler or executable run."""
import json
from pathlib import Path
import stat
import tempfile
import unittest

from dev_build import package_artifacts


class PackageArtifacts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='create-dev-build-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        (self.bundle / 'horizon-mixin.toml').write_text(
            '[mod]\nid = "create"\nversion = "0.6.0-alpha.3"\n', encoding='utf-8')
        (self.bundle / 'a').mkdir()
        (self.bundle / 'a/z.rs').write_text('pub fn nested() {}\n', encoding='utf-8')
        (self.bundle / 'a.rs').write_text('pub fn flat() {}\n', encoding='utf-8')
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        (self.stage / 'native-post-build.json').write_text('[]', encoding='utf-8')
        public = self.stage / 'native-data/create'
        public.mkdir(parents=True)
        self.public_data = b'{"public":true}\n'
        (public / 'content.json').write_bytes(self.public_data)
        self.binary = self.root / 'stub-binary'
        self.binary_bytes = b'developer packaging contract fixture\n'
        self.binary.write_bytes(self.binary_bytes)
        self.binary.chmod(0o751)
        self.destination = self.root / 'artifacts'

    def package(self, **kwargs):
        return package_artifacts(self.binary, self.bundle, self.stage, self.destination,
                                 '1' * 40, kwargs.pop('mixins', None), 'dev', **kwargs)

    def test_metadata_uses_official_filename_order_and_preserves_public_payload(self):
        result = self.package()
        about = json.loads((self.destination / 'native-mods.json').read_text())
        # Frozen from Horizon launcher's name/LE-u64-length/bytes digest contract:
        # a.rs, a/z.rs, horizon-mixin.toml. Path-component sorting reverses the
        # first two. This expected value is not derived from the helper under test;
        # no Rust backend was run to produce this small format fixture.
        expected = 'e4d13e66d271f7aeb378ee7c53ee526ded829d6972dbcaa4025dd43cebe05d16'
        self.assertEqual(result['native_source_digest'], expected)
        self.assertEqual(about['mods'], [dict(id='create', version='0.6.0-alpha.3',
                                            sha256=expected)])
        self.assertEqual(about['horizon'], '1' * 40)
        self.assertIsNone(about['horizon_mixins'])
        self.assertIsNone(about['hooks'])
        self.assertEqual((about['base'], about['profile'], about['target']),
                         ('local-source', 'dev', 'client'))
        self.assertIs(about['developer_build'], True)
        self.assertEqual((self.destination / 'horizon-client').read_bytes(), self.binary_bytes)
        self.assertEqual(stat.S_IMODE((self.destination / 'horizon-client').stat().st_mode),
                         stat.S_IMODE(self.binary.stat().st_mode))
        self.assertEqual(self.binary.read_bytes(), self.binary_bytes)
        self.assertEqual((self.destination / 'native-data/create/content.json').read_bytes(),
                         self.public_data)
        self.assertEqual({p.relative_to(self.destination).as_posix()
                          for p in self.destination.rglob('*') if p.is_file()},
                         {'horizon-client', 'native-mods.json', 'native-data/create/content.json'})

    def test_explicit_base_and_known_mixins_are_preserved(self):
        self.package(mixins='2' * 40, base='nightly-fixture')
        about = json.loads((self.destination / 'native-mods.json').read_text())
        self.assertEqual((about['base'], about['horizon_mixins']),
                         ('nightly-fixture', '2' * 40))

    def test_existing_artifact_directory_is_not_overwritten(self):
        self.destination.mkdir()
        sentinel = self.destination / 'horizon-client'
        sentinel.write_bytes(b'existing artifact')
        with self.assertRaises(FileExistsError):
            self.package()
        self.assertEqual(sentinel.read_bytes(), b'existing artifact')
        self.assertEqual(self.binary.read_bytes(), self.binary_bytes)

    def test_required_post_build_steps_are_not_silently_omitted(self):
        (self.stage / 'native-post-build.json').write_text(
            '[{"mod_id":"create","program":"fixture-not-executed"}]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'post-build steps'):
            self.package()
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.binary.read_bytes(), self.binary_bytes)


if __name__ == '__main__':
    unittest.main()
