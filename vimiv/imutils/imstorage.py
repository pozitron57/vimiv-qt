# vim: ft=python fileencoding=utf-8 sw=4 et sts=4

# This file is part of vimiv.
# Copyright 2017-2019 Christian Karl (karlch) <karlch at protonmail dot com>
# License: GNU GPL v3, see the "LICENSE" and "AUTHORS" files for details.

"""Deals with changing and storing paths to currently loaded images."""

import os
from random import shuffle
from typing import List

from PyQt5.QtCore import QObject

from vimiv import api, utils
from vimiv.commands import search
from vimiv.imutils.imsignals import imsignals
from vimiv.utils import files, slideshow, working_directory, ignore


# We need the check as exif support is optional
try:
    import piexif
except ImportError:
    piexif = None


_paths: List[str] = []
_index = 0


# We want to use the name next here as it is the best name for the command
@api.keybindings.register("n", "next", mode=api.modes.IMAGE)
@api.commands.register()
def next(count: int = 1) -> None:  # pylint: disable=redefined-builtin
    """Select next image.

    **count:** multiplier
    """
    if _paths:
        _set_index((_index + count) % len(_paths))


@api.keybindings.register("p", "prev", mode=api.modes.IMAGE)
@api.commands.register()
def prev(count: int = 1) -> None:
    """Select previous image.

    **count:** multiplier
    """
    if _paths:
        _set_index((_index - count) % len(_paths))


@api.keybindings.register("G", "goto -1", mode=api.modes.IMAGE)
@api.keybindings.register("gg", "goto 1", mode=api.modes.IMAGE)
@api.commands.register(mode=api.modes.IMAGE)
def goto(index: int, count: int = 0) -> None:
    """Select specific image in current filelist.

    **syntax:** ``:goto index``

    positional arguments:
        * index: Number of the image to select.

    .. hint:: -1 is the last image.

    **count:** Select [count]th image instead.
    """
    index = count if count else index
    _set_index(index % (len(_paths) + 1) - 1)


@api.status.module("{abspath}")
def current() -> str:
    """Absolute path to the current image."""
    if _paths:
        return _paths[_index]
    return ""


@api.status.module("{basename}")
def basename() -> str:
    """Basename of the current image."""
    return os.path.basename(current())


@api.status.module("{index}")
def get_index() -> str:  # Needs to be called get as we use index as variable often
    """Index of the current image."""
    if _paths:
        return str(_index + 1).zfill(len(total()))
    return "0"


@api.status.module("{total}")
def total() -> str:
    """Total amount of images."""
    return str(len(_paths))


@api.status.module("{exif-date-time}")
def exif_date_time() -> str:
    """Exif creation date and time of the current image.

    This is meant as an example api.status.module to show how to display exif
    data in the statusbar. If there are any requests/ideas for more, this can
    be used as basis to work with.
    """
    if piexif is not None:
        with ignore(piexif.InvalidImageDataError, FileNotFoundError, KeyError):
            exif_dict = piexif.load(current())
            return exif_dict["0th"][piexif.ImageIFD.DateTime].decode()
    return ""


def pathlist() -> List[str]:
    """Return the currently loaded list of paths."""
    return _paths


class Storage(QObject):
    """Store and move between paths to images.

    Attributes:
        _paths: List of image paths.
        _index: Index of the currently displayed image in the _paths list.
    """

    @api.objreg.register
    def __init__(self):
        super().__init__()
        search.search.new_search.connect(self._on_new_search)
        sshow = slideshow.Slideshow()
        sshow.next_im.connect(self._on_slideshow_event)
        imsignals.open_new_image.connect(self._on_open_new_image)
        imsignals.open_new_images.connect(self._on_open_new_images)

        working_directory.handler.images_changed.connect(self._on_images_changed)

    @utils.slot
    def _on_new_search(
        self, index: int, matches: List[str], mode: api.modes.Mode, incremental: bool
    ):
        """Select search result after new search.

        Incremental search is ignored for images as highlighting the results is
        not possible anyway and permanently loading images is much too
        expensive.

        Args:
            index: Index to select.
            matches: List of all matches of the search.
            mode: Mode for which the search was performed.
            incremental: True if incremental search was performed.
        """
        if _paths and not incremental and mode == api.modes.IMAGE:
            _set_index(index)

    @utils.slot
    def _on_slideshow_event(self):
        next(1)

    @utils.slot
    def _on_open_new_image(self, path: str):
        """Load new image into storage.

        Args:
            path: Path to the new image to load.
        """
        _load_single(os.path.abspath(path))

    @utils.slot
    def _on_open_new_images(self, paths: List[str], focused_path: str):
        """Load list of new images into storage.

        Args:
            paths: List of paths to the new images to load.
            focused_path: The path to display.
        """
        # Populate list of paths in same directory for single path
        if len(paths) == 1:
            _load_single(focused_path)
        else:
            _load_paths(paths, focused_path)

    @utils.slot
    def _on_images_changed(self, paths: List[str]):
        if os.getcwd() != os.path.dirname(current()):
            return
        if paths:
            focused_path = current()
            _load_paths(paths, focused_path)
            api.status.update()
        else:
            _clear()


def _set_index(index: int, previous: str = None) -> None:
    """Set the global _index to index."""
    global _index
    _index = index
    if previous != current():
        imsignals.new_image_opened.emit(current())


def _set_paths(paths: List[str]) -> None:
    """Set the global _paths to paths."""
    global _paths
    _paths = paths
    imsignals.new_images_opened.emit(_paths)


def _load_single(path: str) -> None:
    """Populate list of paths in same directory for single path."""
    if path in _paths:
        goto(_paths.index(path) + 1)  # goto is indexed from 1
    else:
        directory = os.path.dirname(path)
        paths, _ = files.supported(files.listdir(directory))
        _load_paths(paths, path)


def _load_paths(paths: List[str], focused_path: str) -> None:
    """Populate imstorage with a new list of paths.

    Args:
        paths: List of paths to load.
        focused_path: The path to display.
    """
    paths = [os.path.abspath(path) for path in paths]
    focused_path = os.path.abspath(focused_path)
    if api.settings.SHUFFLE.value:
        shuffle(_paths)
    previous = current()
    _set_paths(paths)
    index = (
        paths.index(focused_path)
        if focused_path in paths
        else min(len(paths) - 1, _index)
    )
    _set_index(index, previous)


def _clear() -> None:
    """Clear all images from the storage as all paths were removed."""
    global _paths, _index
    _paths = []
    _index = 0
    imsignals.all_images_cleared.emit()
