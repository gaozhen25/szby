export function pickInitialLinkReference(histories = [], creation = {}) {
  const sourceTaskId = creation.sourceTaskId || "";
  const creationId = creation.creationId || "";

  if (sourceTaskId) {
    const taskBound = histories.find((item) => item.taskId === sourceTaskId);
    if (taskBound) return taskBound;
  }

  if (creationId) {
    return histories.find((item) => item.creationId === creationId) || null;
  }

  return null;
}
