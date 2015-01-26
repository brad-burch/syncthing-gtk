#!/usr/bin/env python2
"""
Syncthing-GTK - EditorDialog

Base class and universal handler for all Syncthing settings and editing
"""

from __future__ import unicode_literals
from gi.repository import Gtk, Gdk, Gio, GObject, GLib
from syncthing_gtk.tools import ints
from syncthing_gtk.daemon import ConnectionRestarted
import os, sys, logging
_ = lambda (a) : a
log = logging.getLogger("EditorDialog")

class EditorDialog(GObject.GObject):
	"""
	Universal dialog handler for all Syncthing settings and editing
	
	Signals:
		close()
			emitted after dialog is closed
		loaded()
			Emitted after dialog loads and parses configuration data
	"""
	__gsignals__ = {
			b"close"	: (GObject.SIGNAL_RUN_FIRST, None, ()),
			b"loaded"	: (GObject.SIGNAL_RUN_FIRST, None, ()),
		}
	
	# Should be overrided by subclass
	MESSAGES = {}
	
	def __init__(self, app, gladefile, title):
		GObject.GObject.__init__(self)
		self.app = app
		self.config = None
		self.values = None
		self.checks = {}
		# Stores original label  value while error message is displayed.
		self.original_labels={}
		# Used by get_widget_id
		self.widget_to_id = {}
		self.setup_widgets(gladefile, title)
	
	def load(self):
		""" Loads configuration data and pre-fills values to fields """
		self.load_data()
	
	def __getitem__(self, name):
		""" Convince method that allows widgets to be accessed via self["widget"] """
		return self.builder.get_object(name)
	
	def __contains__(self, name):
		""" Returns true if there is such widget """
		return self.builder.get_object(name) != None
	
	def get_widget_id(self, w):
		"""
		Returns glade file ID for specified widget or None, if widget
		is not known.
		"""
		if not w in self.widget_to_id:
			return None
		return self.widget_to_id[w]
	
	def find_widget_by_id(self, id, parent=None):
		""" Recursively searchs for widget with specified ID """
		if parent == None:
			if id in self: return self[id] # Do things fast if possible
			parent = self["editor"]
		for c in parent.get_children():
			if hasattr(c, "get_id"):
				if c.get_id() == id:
					return c
			if isinstance(c, Gtk.Container):
				r = self.find_widget_by_id(id, c)
				if not r is None:
					return r
		return None
	
	def show(self, parent=None):
		if not parent is None:
			self["editor"].set_transient_for(parent)
		self["editor"].set_modal(True)
		self["editor"].show_all()
	
	def present(self, values=[]):
		self["editor"].present()
		for v in values:
			if self[v].get_sensitive():
				self[v].grab_focus()
				return
	
	def close(self):
		self.emit("close")
		self["editor"].hide()
		self["editor"].destroy()
	
	def setup_widgets(self, gladefile, title):
		# Load glade file
		self.builder = Gtk.Builder()
		self.builder.add_from_file(os.path.join(self.app.gladepath, gladefile))
		self.builder.connect_signals(self)
		self["editor"].set_title(title)
		# Disable everything until configuration is loaded
		self["editor"].set_sensitive(False)
	
	def get_burried_value(self, key, vals, default, convert=lambda a:a):
		"""
		Returns value stored deeper in element tree.
		Method is called recursively for every tree level. If value is
		not found, default is returned.
		"""
		if type(key) != list:
			# Parse key, split by '/'
			return self.get_burried_value(key.split("/"), vals, default, convert)
		try:
			if len(key) > 1:
				tkey, key = key[0], key[1:]
				return self.get_burried_value(key, vals[tkey], default, convert)
			return convert(vals[key[0]])
		except Exception:
			return default
	
	def get_value(self, key):
		"""
		Returns value from configuration.
		Usualy returns self.values[key], but overriding methods can
		handle some special cases
		"""
		if key in self.values:
			return self.values[key]
		else:
			log.warning("get_value: Value %s not found", key)
			raise ValueNotFoundError(key)
	
	def set_value(self, key, value):
		"""
		Stores value to configuration, handling some special cases in
		overriding methods
		"""
		if key in self.values:
			self.values[key] = value
		else:
			raise ValueNotFoundError(key)
	
	def create_dicts(self, parent, keys):
		"""
		Creates structure of nested dicts, if they are not in place already.
		"""
		if not type(keys) == list: keys = list(keys)
		if len(keys) == 0 : return	# Done
		key, rest = keys[0], keys[1:]
		if not key in parent :
			parent[key] = {}
		if parent[key] in ("", None ):
			parent[key] = {}
		self.create_dicts(parent[key], rest)
	
	def load_data(self):
		self.app.daemon.read_config(self.cb_data_loaded, self.cb_data_failed)
	
	def display_error_message(self, value_id):
		""" Changes text on associated label to error message """
		wid = "lbl%s" % (value_id,) # widget id
		if value_id in self.original_labels:
			# Already done
			return
		if not value_id in self.MESSAGES:
			# Nothing to show
			return
		self.original_labels[value_id] = self[wid].get_label()
		self[wid].set_markup('<span color="red">%s</span>' % (self.MESSAGES[value_id],))
	
	def hide_error_message(self, value_id):
		""" Changes text on associated label back to normal text """
		wid = "lbl%s" % (value_id,) # widget id
		if value_id in self.original_labels:
			self[wid].set_label(self.original_labels[value_id])
			del self.original_labels[value_id]
	
	def cb_data_loaded(self, config):
		""" Used as handler in load_data """
		self.config = config
		if self.on_data_loaded():
			self.update_special_widgets()
			# Enable dialog
			self["editor"].set_sensitive(True)
			# Brag
			self.emit("loaded")
	
	def on_data_loaded(self, config):
		"""
		Called from cb_data_loaded, should be overrided by subclass.
		Should return True to indicate that everything is OK, false on
		error.
		"""
		raise RuntimeError("Override this!")
	
	def display_values(self, values):
		"""
		Iterates over all known configuration values and sets UI
		elements using unholy method.
		Returns True.
		"""
		for key in values:
			widget = self.find_widget_by_id(key)
			self.widget_to_id[widget] = key
			if not key is None:
				try:
					self.display_value(key, widget)
				except ValueNotFoundError:
					# Value not found, probably old daemon version
					log.warning("display_values: Value %s not found", key)
					widget.set_sensitive(False)
		GLib.idle_add(self.present, values)
		return True
		
	def display_value(self, key, w):
		"""
		Sets value on UI element for single key. May be overriden
		by subclass to handle special values.
		"""
		if isinstance(w, Gtk.SpinButton):
			w.get_adjustment().set_value(ints(self.get_value(key.lstrip("v"))))
		elif isinstance(w, Gtk.Entry):
			w.set_text(str(self.get_value(key.lstrip("v"))))
		elif isinstance(w, Gtk.ComboBox):
			val = self.get_value(key.lstrip("v"))
			m = w.get_model()
			for i in xrange(0, len(m)):
				if val == str(m[i][0]).strip():
					w.set_active(i)
					break
		elif isinstance(w, Gtk.CheckButton):
			w.set_active(self.get_value(key.lstrip("v")))
		else:
			log.warning("display_value: %s class cannot handle widget %s, key %s", self.__class__.__name__, w, key)
			if not w is None: w.set_sensitive(False)
	
	def ui_value_changed(self, w, *a):
		"""
		Handler for widget that controls state of other widgets
		"""
		key = self.get_widget_id(w)
		if key != None:
			if isinstance(w, Gtk.CheckButton):
				self.set_value(key.lstrip("v"), w.get_active())
				self.update_special_widgets()
			if isinstance(w, Gtk.ComboBox):
				self.set_value(key.strip("v"), str(w.get_model()[w.get_active()][0]).strip())
				self.update_special_widgets()
	
	def update_special_widgets(self, *a):
		"""
		Enables/disables special widgets. Does nothing by default, but
		may be overrided by subclasses
		"""
		if self.mode == "folder-edit":
			self["vID"].set_sensitive(self.id is None)
			v = self.get_value("Versioning")
			if v == "":
				if self["rvVersioning"].get_reveal_child():
					self["rvVersioning"].set_reveal_child(False)
			else:
				self["bxVersioningSimple"].set_visible(self.get_value("Versioning") == "simple")
				self["bxVersioningStaggered"].set_visible(self.get_value("Versioning") == "staggered")
				if not self["rvVersioning"].get_reveal_child():
					self["rvVersioning"].set_reveal_child(True)
		elif self.mode == "device-edit":
			self["vDeviceID"].set_sensitive(self.is_new)
			self["vAddresses"].set_sensitive(self.id != self.app.daemon.get_my_id())
		elif self.mode == "daemon-settings":
			self["vMaxSendKbps"].set_sensitive(self.get_value("MaxSendKbpsEnabled"))
			self["lblvLocalAnnPort"].set_sensitive(self.get_value("LocalAnnEnabled"))
			self["vLocalAnnPort"].set_sensitive(self.get_value("LocalAnnEnabled"))
			self["lblvGlobalAnnServer"].set_sensitive(self.get_value("GlobalAnnEnabled"))
			self["vGlobalAnnServer"].set_sensitive(self.get_value("GlobalAnnEnabled"))
	
	def cb_data_failed(self, exception, *a):
		"""
		Failed to load configuration. This shouldn't happen unless daemon
		dies exactly when user clicks to edit menu.
		Handled by simple error message.
		"""
		# All other errors are fatal for now. Error dialog is displayed and program exits.
		d = Gtk.MessageDialog(
				self["editor"],
				Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
				Gtk.MessageType.ERROR, Gtk.ButtonsType.CLOSE,
				"%s %s\n\n%s %s" % (
					_("Failed to load configuration from daemon."),
					_("Try again."),
					_("Error message:"), str(exception)
					)
				)
		d.run()
		self.close()
	
	def cb_btClose_clicked(self, *a):
		self.close()
	
	def cb_check_value(self, *a):
		self["btSave"].set_sensitive(True)
		for x in self.checks:
			value = self[x].get_text().strip()
			if len(value) == 0:
				# Empty value in field
				self["btSave"].set_sensitive(False)
				self.hide_error_message(x)
			elif not self.checks[x](value):
				# Invalid value in any field
				self["btSave"].set_sensitive(False)
				self.display_error_message(x)
			else:
				self.hide_error_message(x)
	
	def cb_btSave_clicked(self, *a):
		""" Calls on_save_reuqested to do actual work """
		self.on_save_reuqested()
	
	def on_save_reuqested(self, config):
		"""
		Should be overrided by subclass.
		Should return True to indicate that everything is OK, false on
		error.
		"""
		raise RuntimeError("Override this!")
	
	def store_values(self, values):
		"""
		'values' parameter should be same as display_values recieved.
		Iterates over values configuration values and puts stuff from
		UI back to self.values dict
		Returns True.
		"""
		for key in values:
			widget = self.find_widget_by_id(key)
			if not key is None:
				try:
					self.store_value(key, widget)
				except ValueNotFoundError:
					pass
		return True
	
	def store_value(self, key, w):
		"""
		Loads single value from UI element to self.values dict. May be
		overriden by subclass to handle special values.
		"""
		if isinstance(w, Gtk.SpinButton):
			self.set_value(key.strip("v"), int(w.get_adjustment().get_value()))
		elif isinstance(w, Gtk.Entry):
			self.set_value(key.strip("v"), w.get_text())
		elif isinstance(w, Gtk.CheckButton):
			self.set_value(key.strip("v"), w.get_active())
		elif isinstance(w, Gtk.ComboBox):
			self.set_value(key.strip("v"), str(w.get_model()[w.get_active()][0]).strip())
		# else nothing, unknown widget class cannot be read
	
	def cb_format_value_s(self, spinner):
		""" Formats spinner value  """
		spinner.get_buffer().set_text(_("%ss") % (int(spinner.get_adjustment().get_value()),), -1);
		return True
	
	def cb_format_value_days(self, spinner):
		""" Formats spinner value  """
		v = int(spinner.get_adjustment().get_value())
		if v == 0:
			spinner.get_buffer().set_text(_("never delete"), -1)
		elif v == 1:
			spinner.get_buffer().set_text(_("%s day") % (v,), -1);
		else:
			spinner.get_buffer().set_text(_("%s days") % (v,), -1);
		return True
	
	def post_config(self):
		""" Posts edited configuration back to daemon """
		self["editor"].set_sensitive(False)
		self.app.daemon.write_config(self.config, self.syncthing_cb_post_config, self.syncthing_cb_post_error)
	
	def syncthing_cb_post_config(self, *a):
		# No return value for this call, let's hope for the best
		log.info("Configuration (probably) saved")
		# Close editor
		self["editor"].set_sensitive(True)
		self.on_saved()
	
	def on_saved(self):
		"""
		Should be overrided by subclass.
		Called after post_config saves configuration.
		"""
		raise RuntimeError("Override this!")
	
	def syncthing_cb_post_error(self, exception, *a):
		# TODO: Unified error message
		if isinstance(exception, ConnectionRestarted):
			# Should be ok, this restart is triggered
			# by App handler for 'config-saved' event.
			return self.syncthing_cb_post_config()
		d = Gtk.MessageDialog(
			self["editor"],
			Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
			Gtk.MessageType.INFO, Gtk.ButtonsType.CLOSE,
			"%s\n%s" % (
				_("Failed to save configuration."),
				str(exception)
			))
		d.run()
		d.hide()
		d.destroy()
		self["editor"].set_sensitive(True)
	
	def call_after_loaded(self, callback, *data):
		""" Calls callback when 'loaded' event is emited """
		self.connect("loaded",
			# lambda bellow throws 'event_source' argument and
			# calls callback with rest of arguments
			lambda obj, callback, *a : callback(*a),
			callback, *data
			)

class ValueNotFoundError(KeyError): pass
