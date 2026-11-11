#!/usr/bin/env python3
"""Parse the pinned MIT Create contact methods with the JDK compiler tree API.

This reads only Create source via git show and parses without resolving imported
types. No NeoForge implementation, Minecraft JAR, game, display or account is
used. This establishes source phase/guard mappings; it is not runtime parity.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from common import CREATE, PINS, ROOT

CLASSES = {
    'BasinBlock': 'content/processing/basin/BasinBlock.java',
    'MillstoneBlock': 'content/kinetics/millstone/MillstoneBlock.java',
}
PARSER = r'''
import com.sun.source.tree.*;
import com.sun.source.util.*;
import java.util.*;
import javax.tools.*;

public final class ContactTree {
    static String quote(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
            .replace("\n", "\\n").replace("\r", "\\r") + "\"";
    }
    static String array(List<String> values) {
        return "[" + String.join(",", values.stream().map(ContactTree::quote).toList()) + "]";
    }
    static List<String> calls(Tree node) {
        var result = new ArrayList<String>();
        new TreeScanner<Void, Void>() {
            @Override public Void visitMethodInvocation(MethodInvocationTree call, Void p) {
                super.visitMethodInvocation(call, p);
                ExpressionTree selector = call.getMethodSelect();
                String name = selector instanceof MemberSelectTree member
                    ? member.getIdentifier().toString() : selector.toString();
                result.add(name);
                return null;
            }
        }.scan(node, null);
        return result;
    }
    public static void main(String[] paths) throws Exception {
        var compiler = ToolProvider.getSystemJavaCompiler();
        try (var files = compiler.getStandardFileManager(null, null, null)) {
            var units = files.getJavaFileObjects(paths);
            var task = (JavacTask) compiler.getTask(null, files, null,
                List.of("-proc:none"), null, units);
            for (var unit : task.parse()) {
                new TreeScanner<Void, Void>() {
                    @Override public Void visitMethod(MethodTree method, Void p) {
                        if (!method.getName().contentEquals("updateEntityAfterFallOn"))
                            return null;
                        var statements = new ArrayList<String>();
                        for (var statement : method.getBody().getStatements()) {
                            String condition = statement instanceof IfTree branch
                                ? branch.getCondition().toString() : "";
                            statements.add("{\"kind\":" + quote(statement.getKind().name())
                                + ",\"calls\":" + array(calls(statement))
                                + ",\"condition\":" + quote(condition) + "}");
                        }
                        System.out.println("{\"file\":" + quote(unit.getSourceFile().getName())
                            + ",\"statements\":[" + String.join(",", statements) + "]}");
                        return null;
                    }
                }.scan(unit, null);
            }
        }
    }
}
'''


def java_tools():
    """Prefer the caller's JDK; validate both tools instead of trusting macOS shims."""
    candidates = []
    if os.environ.get('JAVA_HOME'):
        candidates.append(Path(os.environ['JAVA_HOME']) / 'bin')
    if found := shutil.which('javac'):
        candidates.append(Path(found).parent)
    from reference_java import JAVA
    candidates.extend([JAVA / 'bin', Path('/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin')])
    for directory in candidates:
        tools = [directory / name for name in ('javac', 'java')]
        if not all(path.is_file() for path in tools):
            continue
        if all(subprocess.run([str(path), '-version'], capture_output=True).returncode == 0 for path in tools):
            return tools
    raise SystemExit('Set JAVA_HOME to a JDK with javac and java (21 or later).')


def run():
    javac, java = java_tools()
    scratch = Path(tempfile.mkdtemp(prefix='item-contact-source-', dir=ROOT / '.local'))
    files = []
    for name, path in CLASSES.items():
        source = subprocess.check_output([
            'git', 'show', PINS['create_revision'] +
            ':src/main/java/com/simibubi/create/' + path,
        ], cwd=CREATE)
        file = scratch / (name + '.java')
        file.write_bytes(source)
        files.append(file)
    parser = scratch / 'ContactTree.java'
    parser.write_text(PARSER)
    subprocess.run([str(javac), '-d', str(scratch), str(parser)], check=True)
    raw = subprocess.check_output([
        str(java), '-cp', str(scratch), 'ContactTree', *map(str, files),
    ], text=True)
    rows = {Path(r['file']).stem: r for line in raw.splitlines() if (r := json.loads(line))}
    assert set(rows) == set(CLASSES), rows
    basin, millstone = (rows[name]['statements'] for name in CLASSES)
    assert [s['kind'] for s in basin] == ['EXPRESSION_STATEMENT', 'IF', 'IF', 'IF', 'EXPRESSION_STATEMENT']
    assert basin[0]['calls'] == ['updateEntityAfterFallOn']
    assert basin[1]['calls'] == ['blockPosition', 'getBlockState', 'is']
    assert basin[3]['calls'] == ['isAlive']
    assert basin[-1]['calls'][-1] == 'withBlockEntityDo'
    assert all('isClientSide' not in s['condition'] for s in basin)
    assert millstone[0]['calls'] == ['updateEntityAfterFallOn']
    assert 'isClientSide' in millstone[1]['condition']
    assert millstone[3]['calls'] == ['isAlive']
    loop = next(s for s in millstone if s['kind'] == 'ENHANCED_FOR_LOOP')
    assert loop['calls'][:2] == ['blockPosition', 'hereAndBelow']
    all_calls = [c for s in millstone for c in s['calls']]
    assert all_calls.index('getCapability') < all_calls.index('insertItem') < all_calls.index('discard') < all_calls.index('setItem')
    report = {'passed': True, 'source': PINS['create_revision'], 'scope': __doc__, 'methods': rows}
    path = scratch / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'result': str(path)}))
    return report


if __name__ == '__main__':
    run()
