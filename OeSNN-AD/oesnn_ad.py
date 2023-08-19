"""
    Module zawiera główną klasę algorytmu, stanowiącą główny interfejs modelu.
"""

from typing import List, Generator

import numpy as np
import numpy.typing as npt

from layer import InputLayer, OutputLayer
from neuron import OutputNeuron, InputNeuron


class OeSNNAD:
    """
        Klasa implementująca całościowo algorytm OeSNN-AD. Strumień danych
        jest przekazywany jako parametr w konstruktorze, wraz z wszystkimi
        hiperparametrami algorytmu. Głównym interfejsem klasy jest metoda 
        predict, która zwraca wektor z detekcjami.
    """

    def __init__(self, stream: npt.NDArray[np.float64], window_size: int = 100,
                 num_in_neurons: int = 10, num_out_neurons: int = 50,
                 ts_factor: float = 1000.0, mod: float = 0.6, c_factor: float = 0.6,
                 epsilon: float = 2, ksi: float = 0.9, sim: float = 0.15,
                 beta: float = 1.6) -> None:
        """
        _summary_

        Args:
            stream (npt.NDArray[np.float64]): _description_
            window_size (int): _description_. Defaults to 100.
            num_in_neurons (int): _description_. Defaults to 10.
            num_out_neurons (int): _description_. Defaults to 50.
            ts_factor (float): _description_. Defaults to 1000.0.
            mod (float): _description_. Defaults to 0.6.
            c_factor (float): _description_. Defaults to 0.6.
            epsilon (float): _description_. Defaults to 2.
            ksi (float): _description_. Defaults to 0.9.
            sim (float): _description_. Defaults to 0.15.
            beta (float): _description_. Defaults to 1.6.
        """
        self.stream = stream
        self.stream_len = self.stream.shape[0]
        self.window_size = window_size

        self.input_layer: InputLayer = InputLayer(num_in_neurons)
        self.output_layer: OutputLayer = OutputLayer(num_out_neurons)

        self.ts_factor = ts_factor
        self.mod = mod
        self.c_factor = c_factor

        self.gamma = self.c_factor * \
            (1 - self.mod**(2*num_in_neurons)) / (1 - self.mod**2)
        self.epsilon = epsilon
        self.ksi = ksi
        self.sim = sim
        self.beta = beta

        self.values: List[float] = []
        self.anomalies: List[bool] = []
        self.errors: List[float] = []

    def _get_window_from_stream(self, begin_idx: int,
                                end_idx: int) -> npt.NDArray[np.float64]:
        """
            Metoda zwracająca okno z danymi.

            Args:
                begin_idx (int): _description_
                end_idx (int): _description_
                
            Returns:
                npt.NDArray[np.float64]: _description_
        """
        return self.stream[begin_idx: end_idx]

    def _init_values_rand(self, window: npt.NDArray[np.float64]) -> List[float]:
        """
            Docstring here

            Args:
                window (npt.NDArray): _description_
                
            Returns:
                List[float]: _description_
        """
        # TODO: dodaj testy
        return np.random.normal(
            np.mean(window), np.std(window), self.window_size).tolist()

    def _init_new_arrays_for_predict(self, window: npt.NDArray[np.float64]) -> None:
        """
            Metoda inicjalizująca/resetująca listy z wartościami, które tworzone
            są przez czas działania algorytmu tj. listy wartości, błędów i anomalii.

            Args:
                window (npt.NDArray[np.float64]): _description_
                
            Returns:
                List[float]: _description_
        """
        self.values = self._init_values_rand(window)
        self.errors = [np.abs(xt - yt) for xt, yt in zip(window, self.values)]
        self.anomalies = [False] * self.window_size

    def predict(self) -> npt.NDArray[np.bool_]:
        """
            Metoda będąca głównym interfejsem klasy. To tutaj znajduje się
            główny flow algorytmu. Wynikiem działania metody jest wektor z detekcjami.

            Returns:
                npt.NDArray[np.bool_]: _description_
        """
        window = self._get_window_from_stream(0, self.window_size)

        self._init_new_arrays_for_predict(window)
        for age in range(self.window_size + 1, self.stream_len):
            self.input_layer.set_orders(
                window, self.ts_factor, self.mod, self.beta)

            window = self._get_window_from_stream(age - self.window_size, age)

            self._learning(window, age)

            self._anomaly_detection(window)

        return np.array(self.anomalies)

    def _anomaly_detection(self, window: npt.NDArray[np.float64]) -> None:
        """
            Metoda odpowiadająca za sprawdzanie czy zaszła anomalia.

            Args:
                window (npt.NDArray[np.float64]): _description_
        """
        window_head = window[-1]
        first_fired_neuron = self._fires_first()
        if first_fired_neuron:
            self.values.append(first_fired_neuron.output_value)
            self.errors.append(first_fired_neuron.error_calc(window_head))
            self.anomalies.append(self._anomaly_classification())
        else:
            self.values.append(None)
            self.errors.append(np.abs(window_head))
            self.anomalies.append(True)

    def _anomaly_classification(self) -> bool:
        """
            Metoda obliczająca, czy na podstawie ostatniej iteracji algorytmu, głowa okna jest
            anomalią.
            
            Args: None
            
            Returns:
                bool: _description_
        """
        error_t = self.errors[-1]
        errors_window = np.array(self.errors[-(self.window_size):-1])
        anomalies_window = np.array(self.anomalies[-(self.window_size - 1):])

        errors_for_non_anomalies = errors_window[np.where(~anomalies_window)]
        #TODO: Zadługie, wydziel osobną metodę do tego
        return not (
            (not np.any(errors_for_non_anomalies)) or (error_t - np.mean(errors_for_non_anomalies)
                                                < np.std(errors_for_non_anomalies) * self.epsilon)
        )

    def _learning(self, window: npt.NDArray[np.float64], neuron_age: int) -> None:
        """
            Metoda odpowiadająca za naukę i strojenie parametrów sieci.

            Args:
                window (npt.NDArray[np.float64]): _description_
                neuron_age (int): _description_
        """
        anomaly_t, window_head = self.anomalies[-1], window[-1]
        candidate_neuron = self.output_layer.make_candidate(window, self.input_layer.orders,
                                                            self.mod, self.c_factor, neuron_age)

        if not anomaly_t:
            candidate_neuron.error_correction(window_head, self.ksi)

        most_familiar_neuron, dist = self.output_layer.find_most_similar(
            candidate_neuron)

        if dist <= self.sim:
            most_familiar_neuron.update_neuron(candidate_neuron)
        elif self.output_layer.num_neurons < self.output_layer.max_outpt_size:
            self.output_layer.add_new_neuron(candidate_neuron)
        else:
            self.output_layer.replace_oldest(candidate_neuron)

    def _update_psp(self, neuron_input: InputNeuron) -> Generator[OutputNeuron, None, None]:
        """
            Metoda uaktualniąca potencjał postsynaptyczny dla neuronów wyjściowych połączonych z 
            neuronem wejściowym przekazywanym jako parametr funkcji.

            Metoda ta powinna być wywoływana tylko w metodzie _fires_first.
            
            Args:
                neuron_input (InputNeuron): _description_
                
            Yields:
                Generator[OutputNeuron, None, None]: _description_
        """
        for n_out in self.output_layer:
            n_out.update_psp(n_out[neuron_input.neuron_id] * (self.mod ** neuron_input.order))

            if n_out.psp > self.gamma:
                yield n_out

    def _fires_first(self) -> OutputNeuron | bool:
        """
            Metoda kontrolująca działanie potencjału postsynaptycznego w sieci, oraz
            zwracająca pierwszy wystrzeliwujący neuron z posortowanej po order warstwy wejściowej.
            
            Returns:
                OutputNeuron | bool: _description_
        """
        self.output_layer.reset_psp()

        for neuron_input in self.input_layer:
            to_fire = list(self._update_psp(neuron_input))

            if to_fire:
                return max(to_fire, key=lambda x: x.psp)
        return False
