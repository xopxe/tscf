"""Simulation module"""
from time import time
import numpy as np

from tracer.pymobility.models.mobility import random_waypoint
from tracer.pymobility.models.mobility import random_direction
from tracer.pymobility.models.mobility import random_walk
from tracer.pymobility.models.mobility import stochastic_walk

from tracer.towers import TowersManager
from tracer.utils import softmax
from tracer.utils import xamtfos


MOBILITY_MODELS = {
    'random_waypoint': random_waypoint,
    'random_direction': random_direction,
    'random_walk': random_walk,
    'stochastic_walk': stochastic_walk,
}


class TraceSimulator(object):
    """A simulator of user traces"""

    def __init__(
            self,
            number_towers=100,
            number_users=100,
            number_cycles=24,
            method='distance_distribution',
            expander=1,
            sigma=0.03,
            distance_power=5,
            vel_friction=0.9,
            random_towers=False,
            verbose=False,
    ):
        self.number_towers = number_towers
        self.number_users = number_users
        self.number_cycles = number_cycles

        self.method = method

        # for distance_distribution method
        self.expander = expander
        self.sigma = sigma

        # for distance_square method
        self.distance_power = distance_power

        self.random_towers = random_towers
        self.vel_friction = vel_friction
        self.verbose = verbose

    def print(self, *args):
        """Custom print function"""
        if self.verbose:
            print(*args)

    def generate(self):
        """Runs all the simulation"""
        t_0 = time()

        if self.random_towers:
            self.towers = np.random.rand(self.number_towers, 2)
        else:
            step = np.ceil(np.sqrt(self.number_towers)).astype('int')

            if step ** 2 != self.number_towers:
                self.number_towers = step ** 2
                print(
                    f'WARNING: number of towers changed to {self.number_towers}')

            maxXY = 1 - 1 / step
            X, Y = np.mgrid[0:maxXY:step * 1j, 0:maxXY:step * 1j]
            positions = np.vstack([X.ravel(), Y.ravel()])
            self.towers = positions.swapaxes(1, 0)
            # Pad the towers to the center of the cell
            self.towers += 1 / (2 * step)

        self.towers_manager = TowersManager(self.towers, self.vel_friction)

        self.distances = self.towers_manager.distances
        self.print(f'Took {time() - t_0} to create distrances matrix')

        t = time()
        self.probabilities = self.generate_probabilities()
        self.print(f'Took {time() - t} to create probabilities matrix')

        t = time()
        self.traces = self.generate_weighted_users_traces()
        self.print(f'Took {time() - t} to create user traces')

        t = time()
        self.aggregated_data = self.generate_aggregate_data()
        self.print(f'Took {time() - t} to build aggregated data')

        self.print(f'Took {time() - t_0} to generate all')

    def generate_probabilities(self):
        """Generate a matrix of probilities to go from """
        dists = np.copy(self.distances)

        for i in range(self.number_towers):
            for j in range(self.number_towers):
                if self.method == 'distance_distribution':
                    dists[i][j] = (
                        -1 *
                        (dists[i][j] ** 2) *
                        xamtfos(dists[i][j] ** 2, self.sigma) *
                        self.expander
                    )
                elif self.method == 'distance_square':
                    dists[i][j] = -1 * (dists[i][j] + 1) ** self.distance_power

        normalizer = dists.max().max() / 2
        dists -= normalizer

        return np.array([
            softmax(dists[i])
            for i in range(self.number_towers)
        ])

    def generate_weighted_users_traces(self):
        """Generate for each user a random trace of length number_cycles

        It takes into account the direction of the users movements through time.
        """
        def generate_weighted_user_trace():
            towers_ids = np.arange(self.number_towers)

            trace = []
            direction = []
            for cycle in range(self.number_cycles):
                if cycle == 0:
                    # For the first towers the chance of selecting a tower is equally distributed
                    tower = np.random.choice(towers_ids)
                    trace.append(tower)
                    direction.append(self.towers[tower])
                elif cycle == 1:
                    last_tower = trace[cycle - 1]
                    tower = np.random.choice(
                        towers_ids, p=self.probabilities[last_tower])
                    trace.append(tower)
                    direction.append(self.towers[tower])
                else:
                    new_point = self.towers_manager.get_new_point(direction)
                    nearest_tower = \
                        self.towers_manager.get_nearest_tower(new_point)
                    tower = np.random.choice(
                        towers_ids, p=self.probabilities[nearest_tower])
                    trace.append(tower)
                    direction = [direction[1], self.towers[tower]]

            return trace

        return np.array([
            generate_weighted_user_trace()
            for _ in range(self.number_users)
        ])

    def generate_aggregate_data(self):
        """Returns how many users were in each step of the cycle based on traces

        Returns a matrix of shape (number_cycles, number_towers)"""
        return np.array([
            np.sum(self.traces == tower, axis=0)
            for tower in range(self.number_towers)
        ]).T


class MobilitySimulator(object):
    """A simulator of mobility models for user traces"""

    def __init__(
            self,
            number_towers,
            number_users=100,
            number_cycles=24,
            velocity=(0.1, 0.3),
            wait_time_max=1,
            mobility_model='random_waypoint',
            repeat=1,
            random_towers=False,
            verbose=False
    ):
        self.number_towers = number_towers
        self.number_users = number_users
        self.number_cycles = number_cycles
        self.velocity = velocity
        self.wait_time_max = wait_time_max
        self.repeat = repeat
        self.random_towers = random_towers
        self.verbose = verbose

        self.model = MOBILITY_MODELS[mobility_model](
            self.number_users,
            dimensions=(1, 1),
            velocity=self.velocity,
            wt_max=self.wait_time_max,
        )

    def print(self, *args):
        """Custom print function"""
        if self.verbose:
            print(*args)

    def generate_traces(self):
        """Generate users traces though the simulation space"""
        traces = np.array([
            np.copy(next(self.model))
            for _ in range(self.number_cycles)
        ])
        return traces.swapaxes(0, 1)

    def generate_tower_traces(self):
        """Generates a trace of towers for each user

        Transform the users positions thoughout the simulation space into a list of towers
        by choosing the nearest tower for each of the points of the traces of the users.
        """
        results = []
        for trace in self.traces_points:
            results.append([self.towers_manager.get_nearest_tower(x)
                            for x in trace])
        return np.tile(np.array(results), self.repeat)

    def generate_aggregate_data(self):
        """Returns how many users were in each step of the cycle based on traces

        Returns a matrix of shape (number_cycles, number_towers)"""
        return np.array([
            np.sum(self.traces == tower, axis=0)
            for tower in range(self.number_towers)
        ]).T

    def generate(self):
        """Generate user traces using the mobility model and calculates the aggregated data"""
        t_0 = time()
        if self.random_towers:
            self.towers = np.random.rand(self.number_towers, 2)
        else:
            step = np.ceil(np.sqrt(self.number_towers)).astype('int')

            if step ** 2 != self.number_towers:
                self.number_towers = step ** 2
                print(
                    f'WARNING: number of towers changed to {self.number_towers}')

            maxXY = 1 - 1 / step
            X, Y = np.mgrid[0:maxXY:step * 1j, 0:maxXY:step * 1j]
            positions = np.vstack([X.ravel(), Y.ravel()])
            self.towers = positions.swapaxes(1, 0)
            # Pad the towers to the center of the cell
            self.towers += 1 / (2 * step)

        self.towers_manager = TowersManager(self.towers)

        self.traces_points = self.generate_traces()
        self.traces = self.generate_tower_traces()
        self.aggregated_data = self.generate_aggregate_data()

        self.print(f'Took {time() - t_0} to generate all')
