from cat4py import container_ext as ext
import numpy as np
import msgpack


class ReadIter(ext.ReadIter):
    def __init__(self, arr, blockshape):
        self.arr = arr
        super(ReadIter, self).__init__(arr, blockshape)

    def __next__(self):
        buff, info = ext.ReadIter.__next__(self)
        arr = np.frombuffer(buff, dtype=self.arr.dtype).reshape(info.shape)
        return arr, info


class WriteIter(ext.WriteIter):
    def __init__(self, arr):
        self.arr = arr
        super(WriteIter, self).__init__(arr)

    def __next__(self):
        buff, info = ext.WriteIter.__next__(self)
        arr = np.frombuffer(buff, dtype=self.arr.dtype).reshape(info.shape)
        return arr, info


def process_key(key, ndim):
    if not isinstance(key, (tuple, list)):
        key = (key,)
    key = tuple(k if isinstance(k, slice) else slice(k, k + 1) for k in key)
    if len(key) < ndim:
        key += tuple(slice(None) for _ in range(ndim - len(key)))
    return key


class NPArray(ext.Container):

    def __init__(self, dtype=np.float32, **kwargs):
        """The basic and multidimensional and type-less data container.

        Parameters
        ----------
        dtype: numpy.dtype
            The dtype of the container elements.  Default: np.float32.
        pshape: iterable object or None
            The partition shape.  If None, the store is a plain buffer (non-compressed).
        filename: str or None
            The name of the file to store data.  If `None`, data is stores in-memory.
        metalayers: dict or None
            A dictionary with different metalayers.  One entry per metalayer:
                key: bytes or str
                    The name of the metalayer.
                value: object
                    The metalayer object that will be (de-)serialized using msgpack.
        cname: string
            The name for the compressor codec.  Default: "lz4".
        clevel: int (0 to 9)
            The compression level.  0 means no compression, and 9 maximum compression.
            Default: 5.
        filters: list
            The filter pipeline.  Default: [cat4py.SHUFFLE]
        filters_meta: list
            The meta info for each filter in pipeline.  An uint8 per slot. Default: [0]
        cnthreads: int
            The number of threads for compression.  Default: 1.
        dnthreads: int
            The number of threads for decompression.  Default: 1.
        blocksize: int
            The blocksize for every chunk in container.  The default is 0 (automatic).
        use_dict: bool
            If a dictionary should be used during compression.  Default: False.

        """
        self.pre_init(dtype, **kwargs)
        super(NPArray, self).__init__(**kwargs)

    @classmethod
    def cast(cls, some_cont):
        assert isinstance(some_cont, Container)
        some_cont.__class__ = cls
        assert isinstance(some_cont, NPArray)
        return some_cont

    def __getitem__(self, key):
        """Return a (multidimensional) slice as specified in `key`.

        Parameters
        ----------
        key: int, slice or sequence of slices
            The index for the slices to be updated.
            Note that `step` parameter is not honored yet in slices.

        Returns
        -------
        numpy.ndarray
            The numpy array with the requested data.
        """
        key = process_key(key, self.ndim)
        buff = super(NPArray, self).__getitem__(key)

        shape = [k.stop - k.start for k in key]
        return np.frombuffer(buff, dtype=self.dtype).reshape(shape)

    def pre_init(self, dtype, **kwargs):
        self.dtype = np.dtype(dtype)
        kwargs["itemsize"] = self.dtype.itemsize
        if "pshape" in kwargs:
            kwargs["metalayers"] = {"numpy": {"dtype": str(self.dtype)}}
        self.kwargs = kwargs

    def iter_read(self, blockshape=None):
        """Iterate over data blocks whose dims are specified in `blockshape`.

        Parameters
        ----------
        blockshape: tuple, list
            The shape in which the data block will be returned.  If `None`,
            the `NPContainer.pshape` will be used as `blockshape`.

        Yields
        ------
        tuple of (block, info)
            block: numpy.array
                The numpy array with the data block.
            info: namedtuple
                Info about the returned data block.  Its structure is:
                namedtuple("IterInfo", "slice, shape, size")
                IterInfo:
                    slice: tuple
                        The coordinates where the data block starts.
                    shape: tuple
                        The shape of the actual data block (it can be
                        smaller than `blockshape` at the edges of the array).
                    size: int
                        The size, in elements, of the block.
        """
        return ReadIter(self, blockshape)

    def iter_write(self):
        """Iterate over non initialized data blocks.

        Yields
        ------
        tuple of (block, info)
            block: numpy.array
                The numpy.array with the data block to be filled.
            info: namedtuple
                Info about the data block to be filled.  Its structure is:
                namedtuple("IterInfo", "slice, shape, size")
                IterInfo:
                    slice: tuple
                        The coordinates where the data block starts.
                    shape: tuple
                        The shape of the actual data block (it can be
                        smaller than `blockshape` at the edges of the array).
                    size: int
                        The size, in elements, of the block.
        """
        return WriteIter(self)

    def copy(self, **kwargs):
        """Copy to a new container whose properties are specified in `kwargs`.

        Returns
        -------
        Container
            A new container that contains the copy.
        """
        arr = NPArray(dtype=self.dtype, **kwargs)
        ext.copy(self, arr)
        return arr

    def to_buffer(self):
        """Return a buffer with the data contents.

        Returns
        -------
        bytes
            The buffer containing the data of the whole Container.
        """
        return ext.to_buffer(self)

    def to_numpy(self):
        """Return a NumPy array with the data contents and `dtype`.

        Returns
        -------
        numpy.ndarray
            The NumPy array object containing the data of the whole Container.
        """
        return np.frombuffer(self.to_buffer(), dtype=self.dtype).reshape(self.shape)

    def has_metalayer(self, name):
        """Whether `name` is an existing metalayer or not.

        Parameters
        ----------
        name: str
            The name of the metalayer to check.

        Returns
        -------
        bool
            True if metalayer exists in `self`; else False.
        """
        return super(TLArray, self).has_metalayer(name)

    def get_metalayer(self, name):
        """Return the `name` metalayer.

        Parameters
        ----------
        name: str
            The name of the metalayer to return.

        Returns
        -------
        bytes
            The buffer containing the metalayer info (typically in msgpack
            format).
        """
        if self.has_metalayer(name) is False:
            return None
        content = super(TLArray, self).get_metalayer(name)

        return msgpack.unpackb(content)

    def update_metalayer(self, name, content):
        """Update the `name` metalayer with `content`.

        Parameters
        ----------
        name: str
            The name of the metalayer to update.
        content: bytes
            The buffer containing the new content for the metalayer.
            Note that the *length* of the metalayer cannot not change,
            else an exception will be raised.

        """
        content = msgpack.packb(content)
        return super(TLArray, self).update_metalayer(name, content)

    def get_usermeta(self):
        """Return the `usermeta` section.

        Returns
        -------
        bytes
            The buffer for the usermeta section (typically in msgpack format,
            but not necessarily).
        """
        content = super(TLArray, self).get_usermeta()
        return msgpack.unpackb(content)

    def update_usermeta(self, content):
        """Update the `usermeta` section.

        Parameters
        ----------
        content: bytes
            The buffer containing the new `usermeta` data that replaces the
            previous one.  Note that the length of the new content can be
            different from the existing one.

        """
        content = msgpack.packb(content)
        return super(TLArray, self).update_usermeta(content)
