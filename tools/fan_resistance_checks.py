#!/usr/bin/env python3
"""Bounded blasting resistance and source-recipe decision checks.

The production helper and complete plan() body are compiled unchanged against
real Horizon ItemStack/component NBT types. Recipe and prototype lookups are
explicit authored contexts. Original Create canProcess/process bodies are
AST-exported unchanged into a separate Java context, not run in a live game.
No NeoForge implementation or cross-version data fixer is used.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess

from burner_material_checks import function
from common import CREATE, HORIZON, PINS, ROOT, environment
from fan_entity_checks import EXPORTER

SOURCE = 'src/main/java/com/simibubi/create/content/kinetics/fan/processing/AllFanProcessingTypes.java'
JAVA = r'''
// Source method bodies: Copyright (c) The Create Team / The Creators of Create.
// Recording contexts: Copyright (c) 2026 create-horizon contributors.
// SPDX-License-Identifier: MIT
import java.io.*;
import java.util.*;
import java.util.function.Predicate;
public class FanResistanceOracle {
    static class RegistryAccess {}
    record ResourceLocation(String path) { String getPath() { return path; } }
    record RecipeHolder<T extends AbstractCookingRecipe>(ResourceLocation id, T value) {}
    static class ItemStack {
        final String item;
        final boolean resistant;
        ItemStack(String item, boolean resistant) { this.item = item; this.resistant = resistant; }
        boolean has(Object component) { return resistant; }
        static boolean isSameItem(ItemStack a, ItemStack b) { return a.item.equals(b.item); }
    }
    static class DataComponents { static final Object FIRE_RESISTANT = new Object(); }
    static class AbstractCookingRecipe {
        final ItemStack result;
        AbstractCookingRecipe(String item) { result = new ItemStack(item, false); }
        ItemStack getResultItem(RegistryAccess unused) { return result; }
    }
    static class SmeltingRecipe extends AbstractCookingRecipe { SmeltingRecipe(String item) { super(item); } }
    static class BlastingRecipe extends AbstractCookingRecipe { BlastingRecipe(String item) { super(item); } }
    static class SmokingRecipe extends AbstractCookingRecipe { SmokingRecipe(String item) { super(item); } }
    static class RecipeType<T extends AbstractCookingRecipe> {
        static final RecipeType<SmeltingRecipe> SMELTING = new RecipeType<>();
        static final RecipeType<BlastingRecipe> BLASTING = new RecipeType<>();
        static final RecipeType<SmokingRecipe> SMOKING = new RecipeType<>();
    }
    record SingleRecipeInput(ItemStack stack) {}
    static class AllRecipeTypes {
        static final Predicate<RecipeHolder<?>> CAN_BE_AUTOMATED = r -> !r.id().getPath().endsWith("_manual_only");
    }
    static class RecipeManager {
        final Map<RecipeType<?>, RecipeHolder<?>> recipes = new HashMap<>();
        @SuppressWarnings("unchecked")
        <T extends AbstractCookingRecipe> Optional<RecipeHolder<T>> getRecipeFor(
                RecipeType<T> type, SingleRecipeInput input, Level level) {
            return Optional.ofNullable((RecipeHolder<T>) recipes.get(type));
        }
        <T extends AbstractCookingRecipe> void put(RecipeType<T> type, int status, T recipe) {
            if (status != 0) {
                recipes.put(type, new RecipeHolder<>(new ResourceLocation(
                        status == 1 ? "input_manual_only" : "input"), recipe));
            }
        }
    }
    static class Level {
        final RecipeManager recipes = new RecipeManager();
        RecipeManager getRecipeManager() { return recipes; }
        RegistryAccess registryAccess() { return new RegistryAccess(); }
    }
    static class RecipeApplier {
        static List<ItemStack> applyRecipeOn(Level level, ItemStack stack, AbstractCookingRecipe recipe, boolean remainder) {
            return List.of(recipe.result);
        }
    }
    static class BlastingType {
        boolean canProcess(ItemStack stack, Level level) @@CAN_PROCESS@@
        List<ItemStack> process(ItemStack stack, Level level) @@PROCESS@@
    }
    public static void main(String[] args) throws Exception {
        var reader = new BufferedReader(new InputStreamReader(System.in));
        String line;
        while ((line = reader.readLine()) != null) {
            var fields = line.split(" ");
            int s = Integer.parseInt(fields[0]), b = Integer.parseInt(fields[1]), k = Integer.parseInt(fields[2]);
            boolean resistant = fields[3].equals("1"), same = fields[4].equals("1");
            var level = new Level();
            String chosen = s == 2 ? "example:smelt" : "example:blast";
            level.recipes.put(RecipeType.SMELTING, s, new SmeltingRecipe("example:smelt"));
            level.recipes.put(RecipeType.BLASTING, b, new BlastingRecipe("example:blast"));
            level.recipes.put(RecipeType.SMOKING, k, new SmokingRecipe(same ? chosen : "example:smoke"));
            var stack = new ItemStack("minecraft:cobblestone", resistant);
            var type = new BlastingType();
            var outputs = type.process(stack, level);
            System.out.println(type.canProcess(stack, level) + ":" +
                    String.join(",", outputs.stream().map(item -> item.item).toList()));
        }
    }
}
'''


def sha(value):
    return hashlib.sha256(value).hexdigest()


def run(args):
    horizon = args.horizon.resolve()
    work = ROOT / '.local/fan-resistance-checks'
    src = work / 'probe/src'
    src.mkdir(parents=True, exist_ok=True)
    native = (ROOT / 'mixins/create/fan.rs').read_text()
    helper = function(native, 'fn blasting_fire_resistance(')
    plan = function(native, 'fn plan(')
    template = (ROOT / 'tools/rust/fan_resistance_probe.rs.in').read_text()
    probe = template.replace('@@HELPER@@', helper).replace('@@PLAN@@', plan)
    (src / 'main.rs').write_text(probe)
    manifest = (
        '[package]\nname="create-fan-resistance-checks"\n'
        'version="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\n'
    )
    for name in ['horizon-items', 'horizon-world']:
        manifest += f'{name}={{path={json.dumps(str(horizon / "crates" / name))}}}\n'
    manifest += 'serde_json="1"\n'
    manifest += '[profile.dev]\ndebug="line-tables-only"\n'
    cargo_manifest = work / 'probe/Cargo.toml'
    cargo_manifest.write_text(manifest)
    shutil.copyfile(horizon / 'Cargo.lock', work / 'probe/Cargo.lock')
    fields = ['smelting', 'blasting', 'smoking', 'resistant', 'same']
    combinations = itertools.product(
        range(3), range(3), range(3), [False, True], [False, True],
    )
    contexts = [dict(zip(fields, values)) for values in combinations]
    env = environment()
    args.target.resolve().relative_to((ROOT / '.local').resolve())
    env.update(CARGO_TARGET_DIR=str(args.target.resolve()), CARGO_BUILD_JOBS='2')
    cargo = [str(ROOT / '.tools/rust/bin/cargo')]
    common = ['--offline', '--manifest-path', str(cargo_manifest)]
    report = {
        'passed': False,
        'scope': __doc__,
        'create_revision': PINS['create_revision'],
        'helper_sha256': sha(helper.encode()),
        'plan_sha256': sha(plan.encode()),
        'native_sha256': sha(native.encode()),
        'horizon_type_files': {
            name: sha((horizon / 'crates/horizon-items/src' / name).read_bytes())
            for name in ['items.rs', 'item_data.rs', 'item_nbt.rs']
        },
        'unsupported_selectors': (
            'Custom/other tags, unmapped direct IDs, aliases and malformed data '
            'retain the stack when no cooking recipe exists.'
        ),
        'commands': [],
    }

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    def command(words, name, **kwargs):
        report['commands'].append({'command': list(map(str, words)), 'log': name})
        save()
        result = subprocess.run(
            list(map(str, words)), env=env, text=True, capture_output=True, **kwargs,
        )
        (work / name).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name} failed; inspect {work / name}')
        return result.stdout

    save()
    tests = command(cargo + ['test'] + common, 'rust-tests.log')
    report['rust_tests'] = int(re.search(r'test result: ok\. (\d+) passed', tests)[1])
    output = command(
        cargo + ['run', '--quiet'] + common,
        'rust-run.log', input=json.dumps(contexts),
    )
    result = json.loads(output)
    report['actual_stack_classifications'] = len(result['classifications'])
    report['classification_statuses'] = result['classifications']
    java_home = args.java_home
    if java_home is None:
        selected = json.loads((ROOT / '.local/java-reference/manifest.json').read_text())
        java_home = Path(selected['java'])
    java = java_home / 'bin/java'
    javac = java_home / 'bin/javac'
    exporter = work / 'ExportEntityMethod.java'
    exporter.write_text(EXPORTER)
    command([javac, '-d', work, exporter], 'javac-exporter.log')
    source = subprocess.check_output(
        ['git', 'show', PINS['create_revision'] + ':' + SOURCE], cwd=CREATE,
    )
    original = work / 'AllFanProcessingTypes.java'
    original.write_bytes(source)
    original_java = JAVA
    for marker, method in [('CAN_PROCESS', 'canProcess'), ('PROCESS', 'process')]:
        body = command(
            [java, '-cp', work, 'ExportEntityMethod', original, 'BlastingType', method],
            f'java-{method}-body.log',
        )
        original_java = original_java.replace('@@' + marker + '@@', body)
    oracle = work / 'FanResistanceOracle.java'
    oracle.write_text(original_java)
    command([javac, '-d', work, oracle], 'javac-oracle.log')
    inputs = '\n'.join(
        ' '.join(str(int(row[key])) for key in fields) for row in contexts
    ) + '\n'
    expected = command(
        [java, '-cp', work, 'FanResistanceOracle'], 'java-run.log', input=inputs,
    ).splitlines()
    assert len(expected) == len(result['recipes']) == len(contexts)
    rejected_old = 0
    for context, original_result, actual in zip(contexts, expected, result['recipes']):
        can_process, outputs = original_result.split(':', 1)
        wanted = can_process == 'true'
        assert actual['can_process'] == wanted, (context, original_result, actual)
        if wanted:
            expected_outputs = [] if not outputs else outputs.split(',')
            assert actual['outputs'] == expected_outputs, (context, original_result, actual)
        old = context['smelting'] == 2 or context['blasting'] == 2 or context['resistant']
        rejected_old += old != wanted
    assert rejected_old > 0
    command(
        cargo + ['clippy'] + common + ['--all-targets', '--', '-D', 'warnings'],
        'clippy.log',
    )
    report.update(
        passed=True, original_method_contexts=len(contexts),
        old_default_only_rejected_contexts=rejected_old,
        original_source_sha256=sha(source),
        java_scope=(
            'Unchanged original method bodies with authored presence and recipe '
            'contexts; not actual Java ItemStack or full NeoForge.'
        ),
    )
    save()
    summary = {
        key: value for key, value in report.items()
        if key not in ['commands', 'classification_statuses']
    }
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizon', type=Path, default=HORIZON)
    parser.add_argument('--target', type=Path, default=ROOT / '.local/fluid-render-target')
    parser.add_argument('--java-home', type=Path)
    run(parser.parse_args())
