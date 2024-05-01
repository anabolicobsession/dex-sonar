class Pool:
    def __init__(self, id):
        self.id = id

    def set(self,
            name = None,
            dex = None,
            m5 = None,
            h1 = None
            ):
        self.name = name
        self.dex = dex
        self.m5 = m5
        self.h1 = h1
        return self

    def __repr__(self):
        return f'{self.name} {self.dex} {self.m5}'


class Pools:
    def __init__(self):
        self.pools = []

    def update(self, id, **params):
        pool = None
        pool_exists = False

        for p in self.pools:
            if p.id == id:
                pool = p
                pool_exists = True
                break

        if pool_exists: pool.set(**params)
        else: self.pools.append(Pool(id).set(**params))

    def __repr__(self):
        return '\n'.join([p.__repr__() for p in self.pools])
