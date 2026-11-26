"""Install the pinned thread affinity policy on the raphael 4.14 scheduler."""

import argparse
import re
from pathlib import Path


CORE_SEAM = "\nlong sched_setaffinity(pid_t pid, const struct cpumask *in_mask)\n"
CPUSET_SEAM = "\t\tWARN_ON_ONCE(update_cpus_allowed(cs, task, cpus_attach));\n"
CORE_INCLUDE = '#include "raphael_sched_affinity.inc"'
CPUSET_INCLUDE = '#include "../sched/ace6_sched_affinity.h"'
KBUILD = "obj-y += ace6_thread_affinity.o"


def replace_once(text, old, new, name):
    if text.count(old) != 1:
        raise SystemExit(f"Cannot locate the expected affinity integration point in {name}")
    return text.replace(old, new)


def install(kernel, source):
    top = (kernel / "Makefile").read_text(encoding="utf-8").splitlines()
    if not {"VERSION = 4", "PATCHLEVEL = 14"}.issubset(top):
        raise SystemExit("Thread affinity requires the reviewed raphael 4.14 scheduler")
    sched_h = (kernel / "include/linux/sched.h").read_text(encoding="utf-8")
    for mask in ("cpus_allowed", "cpus_requested"):
        if not re.search(rf"\bcpumask_t\s+{mask};", sched_h):
            raise SystemExit(f"Missing raphael task affinity field: {mask}")

    sched = kernel / "kernel/sched"
    core = sched / "core.c"
    cpuset = kernel / "kernel/cgroup/cpuset.c"
    kbuild = sched / "Makefile"
    core_text = core.read_text(encoding="utf-8")
    cpuset_text = cpuset.read_text(encoding="utf-8")
    kbuild_text = kbuild.read_text(encoding="utf-8")

    integrated = (CORE_INCLUDE in core_text, CPUSET_INCLUDE in cpuset_text, KBUILD in kbuild_text)
    if any(integrated) and not all(integrated):
        raise SystemExit("Incomplete prior raphael thread affinity integration")
    if not all(integrated):
        core_text = replace_once(core_text, CORE_SEAM, f"\n{CORE_INCLUDE}\n" + CORE_SEAM, core)
        cpuset_text = replace_once(
            cpuset_text, '#include "cgroup-internal.h"\n',
            f'#include "cgroup-internal.h"\n{CPUSET_INCLUDE}\n', cpuset,
        )
        cpuset_text = replace_once(
            cpuset_text, CPUSET_SEAM, CPUSET_SEAM + "\t\traphael_affinity_cpuset_changed(task);\n",
            cpuset,
        )
        kbuild_text += f"\n{KBUILD}\n"

    driver_name = "ace6_thread_affinity.c"
    driver = (source / driver_name).read_text(encoding="utf-8")
    driver = replace_once(
        driver,
        "\tcpumask_copy(&state->effective, &task->cpus_mask);\n"
        "\tstate->has_request = task->user_cpus_ptr != NULL;\n"
        "\tif (state->has_request)\n"
        "\t\tcpumask_copy(&state->requested, task->user_cpus_ptr);\n"
        "\telse\n"
        "\t\tcpumask_clear(&state->requested);",
        "\tcpumask_copy(&state->effective, &task->cpus_allowed);\n"
        "\tcpumask_copy(&state->requested, &task->cpus_requested);\n"
        "\tstate->has_request = !cpumask_empty(&state->requested);",
        driver_name,
    )
    driver = replace_once(
        driver,
        "static void on_cpuset(void *data, struct cgroup_subsys_state *css,\n"
        "\t\t      struct task_struct *task)",
        "void raphael_affinity_cpuset_changed(struct task_struct *task)",
        driver_name,
    )
    driver = replace_once(
        driver, '\t{ "android_vh_cpuset_attach_task", on_cpuset },\n', "", driver_name,
    )
    driver = replace_once(
        driver,
        'MODULE_DESCRIPTION("Rule-driven thread CPU affinity for OnePlus Ace 6");',
        'MODULE_DESCRIPTION("Rule-driven thread CPU affinity for Redmi K20 Pro");',
        driver_name,
    )

    header_name = "ace6_sched_affinity.h"
    header = replace_once(
        (source / header_name).read_text(encoding="utf-8"), "\n#endif\n",
        "\nvoid raphael_affinity_cpuset_changed(struct task_struct *task);\n\n#endif\n",
        header_name,
    )
    compat = Path(__file__).with_name("raphael_sched_affinity.inc")
    files = {
        core: core_text,
        cpuset: cpuset_text,
        kbuild: kbuild_text,
        sched / driver_name: driver,
        sched / header_name: header,
        sched / compat.name: compat.read_text(encoding="utf-8"),
    }
    adaptive_name = "adaptive_policy.h"
    adaptive = (source / adaptive_name).read_text(encoding="utf-8")
    adaptive = replace_once(
        adaptive,
        "\tunsigned int interactive = count <= 4 ? count : count - 2;\n"
        "\tint cpu;\n\n\tfor_each_possible_cpu(cpu) {\n",
        "\tunsigned int interactive = count <= 4 ? count : count - 2;\n"
        "\tunsigned int background = 5;\n"
        "\tint cpu;\n\n"
        "\t/* Raphael has four little cores, three performance cores and one prime core. */\n"
        "\tif (count == 8) {\n"
        "\t\tinteractive = 7;\n"
        "\t\tbackground = little;\n"
        "\t}\n\n\tfor_each_possible_cpu(cpu) {\n",
        adaptive_name,
    )
    adaptive = replace_once(
        adaptive,
        "\t\tif (index < 5)\n\t\t\tcpumask_set_cpu(cpu, &background_cpus);\n",
        "\t\tif (index < background)\n\t\t\tcpumask_set_cpu(cpu, &background_cpus);\n",
        adaptive_name,
    )
    files[sched / adaptive_name] = adaptive
    files[sched / "affinity_rules.h"] = (source / "affinity_rules.h").read_text(encoding="utf-8")
    for path, text in files.items():
        path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    options = parser.parse_args()
    install(options.kernel, options.source)
