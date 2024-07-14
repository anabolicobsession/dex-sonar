from typing import TypeVar, Generic, Iterable


class NotEnoughItemsToPop(Exception):
    ...


T = TypeVar('T')

class CircularList(Generic[T]):
    def __init__(self, capacity):
        self.list: list[T] = [None] * capacity
        self.capacity = capacity
        self.beginning = 0
        self.size = 0

    def __len__(self):
        return self.size

    def __iter__(self):
        return (self.list[(self.beginning + i) % self.capacity] for i in range(self.size))

    def __repr__(self):
        return '[' + ', '.join([repr(item) for item in self]) + ']'

    def append(self, item: T):
        self.list[self._translate_index(self.size)] = item

        if self.size < self.capacity:
            self.size += 1
        else:
            self.beginning = self._translate_index(1)

    def extend(self, iterable: Iterable[T]):
        for item in iterable:
            self.append(item)

    def pop(self, n=1):
        if self.size - n >= 0:
            self.size -= n
        else:
            if not self.size:
                raise NotEnoughItemsToPop('No items to pop')
            else:
                raise NotEnoughItemsToPop(f'There are only {self.size} items to pop ({n} were tried to be popped')

    def clear(self):
        self.size = 0

    def _translate_index(self, i):
        base = self.beginning if i >= 0 else self.beginning + self.size
        return (base + i) % self.capacity

    def __getitem__(self, i: int | slice):

        if isinstance(i, int):
            if not -self.size <= i < self.size:
                raise IndexError(f'Index {i} is out of range [{-self.size}, {self.size})')
            return self.list[self._translate_index(i)]

        else:
            start = i.start if i.start is not None else 0
            stop =  i.stop  if i.stop  is not None else self.size
            step =  i.step  if i.step  is not None else 1

            start = start % self.size
            if stop != self.size: stop = stop % self.size

            # if not (-self.size <= start <= stop <= 0 or 0 <= start <= stop <= self.size):
            #     raise IndexError(f'Slice {i} doesn\'t satisfy condition {-self.size} <= start <= stop <= 0 or 0 <= start <= stop <= {self.size}')

            return [self.list[self._translate_index(j)] for j in range(start, stop, step)]
