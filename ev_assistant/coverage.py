"""Required positions are scan scope, separate from observed slot receipts."""


def sweep_positions(config):
    # Configurations without a scope retain their original full-slot behavior.
    positions = config.get('sweep', {}).get('positions', list(range(1, 22)))
    if (not isinstance(positions, (list, tuple)) or not positions
            or any(type(p) is not int or p not in range(1, 22) for p in positions)
            or len(set(positions)) != len(positions)):
        raise ValueError('Sweep positions must be unique integers between 1 and 21')
    return tuple(sorted(positions))
