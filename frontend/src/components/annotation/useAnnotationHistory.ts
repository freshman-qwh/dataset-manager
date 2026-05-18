import { useCallback, useState } from "react";

import type { AnnotationObject } from "../../types/dataset";

function cloneObjects(objects: AnnotationObject[]): AnnotationObject[] {
  return objects.map((object) => ({
    ...object,
    points: [...object.points],
    flags: { ...object.flags },
    attributes: { ...object.attributes }
  }));
}

export function useAnnotationHistory(initialObjects: AnnotationObject[] = []) {
  const [past, setPast] = useState<AnnotationObject[][]>([]);
  const [present, setPresent] = useState<AnnotationObject[]>(() => cloneObjects(initialObjects));
  const [future, setFuture] = useState<AnnotationObject[][]>([]);

  const reset = useCallback((nextObjects: AnnotationObject[]) => {
    setPast([]);
    setFuture([]);
    setPresent(cloneObjects(nextObjects));
  }, []);

  const replace = useCallback((nextObjects: AnnotationObject[]) => {
    setPresent(cloneObjects(nextObjects));
  }, []);

  const commit = useCallback((nextObjects: AnnotationObject[], previousObjects = present) => {
    setPast((items) => [...items.slice(-49), cloneObjects(previousObjects)]);
    setPresent(cloneObjects(nextObjects));
    setFuture([]);
  }, [present]);

  const undo = useCallback(() => {
    setPast((items) => {
      const previous = items[items.length - 1];
      if (!previous) {
        return items;
      }
      setFuture((futureItems) => [cloneObjects(present), ...futureItems]);
      setPresent(cloneObjects(previous));
      return items.slice(0, -1);
    });
  }, [present]);

  const redo = useCallback(() => {
    setFuture((items) => {
      const next = items[0];
      if (!next) {
        return items;
      }
      setPast((pastItems) => [...pastItems.slice(-49), cloneObjects(present)]);
      setPresent(cloneObjects(next));
      return items.slice(1);
    });
  }, [present]);

  return {
    objects: present,
    reset,
    replace,
    commit,
    undo,
    redo,
    canUndo: past.length > 0,
    canRedo: future.length > 0
  };
}
