"""Pluggable batch bank-payment file formats (ABA, and future NACHA/SEPA/BACS/...).

Each country's banks expect a different bulk-payment upload format. This
package keeps that variation behind one small interface (BankFileFormat in
base.py) so adding a new country's format later never means reworking the
export pipeline in bank_file_export_service.py -- only adding one new module
and registering it in registry.py.
"""
