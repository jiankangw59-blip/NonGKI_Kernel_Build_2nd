/* SPDX-License-Identifier: GPL-2.0 */
#include "ace6_sched_affinity.h"

/* The worker owns a task reference and runs with the rule loader's credentials. */
int ace6_set_task_affinity(struct task_struct *task, const struct cpumask *target,
			  const struct cpumask *requested)
{
	cpumask_t allowed, effective;
	unsigned long flags;
	int ret;

	if (READ_ONCE(task->flags) & (PF_KTHREAD | PF_EXITING | PF_NO_SETAFFINITY))
		return -ESRCH;
	if (task_has_dl_policy(task))
		return -EBUSY;
	if (!check_same_owner(task)) {
		bool permitted;

		rcu_read_lock();
		permitted = ns_capable(__task_cred(task)->user_ns, CAP_SYS_NICE);
		rcu_read_unlock();
		if (!permitted)
			return -EPERM;
	}
	ret = security_task_setscheduler(task);
	if (ret)
		return ret;

	cpuset_cpus_allowed(task, &allowed);
	/* A restored request can be outside the task's current cpuset. */
	if (!cpumask_and(&effective, target, &allowed))
		cpumask_copy(&effective, &allowed);

	for (;;) {
		ret = __set_cpus_allowed_ptr(task, &effective, true);
		if (ret)
			return ret;
		cpuset_cpus_allowed(task, &allowed);
		if (cpumask_subset(&effective, &allowed))
			break;
		/* As in sched_setaffinity(), a concurrent attach takes precedence. */
		cpumask_copy(&effective, &allowed);
	}

	raw_spin_lock_irqsave(&task->pi_lock, flags);
	if (requested)
		cpumask_and(&task->cpus_requested, requested, cpu_possible_mask);
	else
		cpumask_clear(&task->cpus_requested);
	raw_spin_unlock_irqrestore(&task->pi_lock, flags);
	return 0;
}
