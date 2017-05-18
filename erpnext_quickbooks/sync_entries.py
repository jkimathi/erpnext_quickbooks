from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt, cstr, nowdate
import requests.exceptions
from .utils import make_quickbooks_log, pagination
from erpnext.accounts.doctype.journal_entry.journal_entry import get_payment_entry_against_invoice

""" Create Payment entry against Sales Invoices"""

def sync_si_payment(quickbooks_obj):
	"""Get all Payment(Payment Entry) from QuickBooks for all the Received Payment"""
	business_objects = "Payment"
	get_qb_payment = pagination(quickbooks_obj, business_objects)
	if get_qb_payment: 
		# print get_qb_payment, "---------------------------"
		get_payment_received= validate_si_payment(get_qb_payment)
		if get_payment_received:
			sync_qb_journal_entry_against_si(get_payment_received)

def validate_si_payment(get_qb_payment):
	recived_payment = [] 
	payment_against_credit_note = []
	payments = []
	for entries in get_qb_payment:
		if entries.get('DepositToAccountRef'):
			for line in entries['Line']:
				recived_payment.append({
					'Id': entries.get('Id')+"-"+'SI'+"-"+line.get('LinkedTxn')[0].get('TxnId'),
					'Type':	line.get('LinkedTxn')[0].get('TxnType'),
					'ExchangeRate': entries.get('ExchangeRate'),
					'Amount': line.get('Amount')*entries.get('ExchangeRate'),
					'TxnDate': entries.get('TxnDate'),
					'qb_account_id': entries.get('DepositToAccountRef').get('value'),
					'qb_si_id':line.get('LinkedTxn')[0].get('TxnId'),
					'paid_amount': line.get('Amount'),
					"doc_no": entries.get("DocNumber")
					})
		else:
			payment_against_credit_note.append(entries);
			
	if payment_against_credit_note:
		pass 
		# adjust_entries(payment_against_credit_note)
	return recived_payment

def adjust_entries(payment_against_credit_note):
	for entries in payment_against_credit_note:
		payments = []
		for line in entries['Line']:
			payments.append({
				'Id': entries.get('Id')+"-"+'SI'+"-"+line.get('LinkedTxn')[0].get('TxnId'),
				'Type':	line.get('LinkedTxn')[0].get('TxnType'),
				'ExchangeRate': entries.get('ExchangeRate'),
				'Amount': line.get('Amount')*entries.get('ExchangeRate'),
				'TxnDate': entries.get('TxnDate'),
				'qb_si_id': line.get('LinkedTxn')[0].get('TxnId') if line.get('LinkedTxn')[0].get('TxnType') == "Invoice" else None,
				'paid_amount': line.get('Amount'),
				"doc_no": entries.get("DocNumber"),
				"credit_not_id" : line.get('LinkedTxn')[0].get('TxnId')+"CE" if line.get('LinkedTxn')[0].get('TxnType') == "CreditMemo" else None,
				"customer_name" : frappe.db.get_value("Customer",{"quickbooks_cust_id":entries['CustomerRef'].get('value')},"name")
				})
		adjust_journal_entries_against_credit_note(payments)
			# print entries.get('Id'), "data", line 

def adjust_journal_entries_against_credit_note(payments):
	print "\n\n"
	for row in payments:
		if row.get('credit_not_id'):
			print row.get('credit_not_id'), "datatdatatdtatdtatd"
			entry_name = frappe.db.get_value("Journal Entry", {"quickbooks_journal_entry_id": row.get('credit_not_id')}, "name")
			journal_entry = frappe.get_doc("Journal Entry", entry_name)
			account_entry(journal_entry, payments, row)
			# print data.__dict__, "ppppppppppppppp"
		# print payments, "hello"
def account_entry(journal_entry, payments, credit_memo):
	account = []
	credit_entry = {}
	advance_entry = {}
	total_amount =  0
	debit_to = ""
	for row in journal_entry.accounts:
		if row.get('debit_in_account_currency'):
			total_amount = flt(row.get('debit_in_account_currency'))
			account.append(row)
			journal_entry.append("accounts", row)
	for invoice in payments:
		if invoice.get("Type") == "Invoice":
			invoice_name = frappe.db.get_value("Sales Invoice", {"quickbooks_invoce_id": invoice.get('qb_si_id') }, "name")
			
			invoice = frappe.get_doc("Sales Invoice", invoice_name)
			account = journal_entry.append("accounts", {})
			account.credit_in_account_currency = flt(invoice.get('paid_amount'))
			account.party_type = "Customer"
			account.party = invoice.get('customer_name')
			account.account = invoice.get('debit_to')
			account.reference_type = "Sales Invoice"
			account.reference_name = invoice_name
			account.is_advance = "Yes"
			debit_to = invoice.get('debit_to')
		
			# credit_entry['credit_in_account_currency'] = flt(invoice.get('paid_amount'))
			# credit_entry['party_type'] = "Customer"
			# credit_entry['party'] = invoice.get('customer_name')
			# credit_entry['account'] = invoice.get('debit_to')
			# credit_entry['reference_type'] = "Sales Invoice"
			# credit_entry['reference_name'] = invoice_name
			# credit_entry['is_advance'] = "Yes"
			# account.append(credit_entry)
		else:
			account = journal_entry.append("accounts", {})
			account.credit_in_account_currency = flt(total_amount) - flt(credit_memo.get('paid_amount'))
			account.account = debit_to
			account.is_advance = "Yes"
			# advance_entry['credit_in_account_currency'] = flt(total_amount) - flt(credit_memo.get('paid_amount'))
			# advance_entry['account'] =  debit_to
			# advance_entry['is_advance'] = "Yes"
	account.append(advance_entry)
	
	# journal_entry.update("accounts":account)
	print account, "-------------------"				

	# for row in journal_entry.accounts:
	# 	if row.get('debit_in_account_currency'):
	# 		account.extend(row)
	# journal_entry.update({"account" : account})
		

def sync_qb_journal_entry_against_si(get_payment_received):
	quickbooks_settings = frappe.get_doc("Quickbooks Settings", "Quickbooks Settings")
	for recived_payment in get_payment_received:
 		try:
 			if not frappe.db.get_value("Payment Entry", {"quickbooks_payment_id": recived_payment.get('Id')}, "name"):
 				create_payment_entry_si(recived_payment, quickbooks_settings)
 		except Exception, e:
 			make_quickbooks_log(title=e.message, status="Error", method="sync_qb_journal_entry_against_si", message=frappe.get_traceback(),
						request_data=recived_payment, exception=True)


def create_payment_entry_si(recived_payment, quickbooks_settings):
	""" create payment entry against sales Invoice """
	invoice_name =frappe.db.get_value("Sales Invoice", {"quickbooks_invoce_id": recived_payment.get('qb_si_id')}, "name")
	account_ref = get_account_detail(recived_payment.get('qb_account_id'))
	if invoice_name:
		ref_doc = frappe.get_doc("Sales Invoice", invoice_name)
		si_pe = frappe.new_doc("Payment Entry")
		si_pe.naming_series = "SI-PE-QB-"
		si_pe.quickbooks_invoice_reference_no = ref_doc.get('quickbooks_invoice_no')
		si_pe.quickbooks_payment_reference_no = recived_payment.get('doc_no')
		si_pe.posting_date = recived_payment.get('TxnDate')
		si_pe.quickbooks_payment_id = recived_payment.get('Id')
		si_pe.payment_type = "Receive"
		si_pe.party_type = "Customer"
		si_pe.party = ref_doc.customer_name
		si_pe.paid_from = ref_doc.get("debit_to")
		# si_pe.paid_to = account_ref.get('name')
		si_pe.paid_amount= flt(recived_payment.get('paid_amount'), si_pe.precision('paid_amount'))
		si_pe.source_exchange_rate = recived_payment.get('ExchangeRate')
		si_pe.base_paid_amount = flt(recived_payment.get('paid_amount') * recived_payment.get('ExchangeRate'), si_pe.precision('base_paid_amount'))
		si_pe.base_received_amount = flt(recived_payment.get('paid_amount') * recived_payment.get('ExchangeRate'), si_pe.precision('base_received_amount'))
		si_pe.allocate_payment_amount = 1
		si_pe.reference_no = recived_payment.get('Type')
		si_pe.reference_date = recived_payment.get('TxnDate')

		get_accounts(si_pe, ref_doc, recived_payment, quickbooks_settings)
		get_reference(dt= "Sales Invoice", pay_entry_obj= si_pe, ref_doc= ref_doc, ref_pay= recived_payment, quickbooks_settings= quickbooks_settings)
		get_deduction(dt= "Sales Invoice", pay_entry_obj= si_pe, ref_doc= ref_doc, ref_pay= recived_payment, quickbooks_settings= quickbooks_settings)
		
		si_pe.flags.ignore_mandatory = True
		si_pe.save(ignore_permissions=True)
		si_pe.submit()
		frappe.db.commit()

def get_accounts(si_pe, ref_doc, recived_payment, quickbooks_settings):
	company_name = quickbooks_settings.select_company
	company_currency = frappe.db.get_value("Company", {"name": company_name}, "default_currency")
	account_ref = get_account_detail(recived_payment.get('qb_account_id'))
	si_pe.paid_to = account_ref.get('name')
	if account_ref.get('account_currency') == company_currency:
		si_pe.target_exchange_rate = 1
		si_pe.received_amount = flt(recived_payment.get('paid_amount') * recived_payment.get('ExchangeRate'), si_pe.precision('received_amount'))
	else:
		si_pe.target_exchange_rate = recived_payment.get('ExchangeRate')
		si_pe.received_amount = flt(recived_payment.get('paid_amount') , si_pe.precision('received_amount'))


""" Create Payment entry against Purchase Invoices""" 

def sync_pi_payment(quickbooks_obj):
	"""Get all BillPayment(Payment Entry) from QuickBooks for all the paid Bills"""
	business_objects = "BillPayment"
	get_qb_billpayment = pagination(quickbooks_obj, business_objects)
	if get_qb_billpayment:  
		get_bill_pi= validate_pi_payment(get_qb_billpayment)
		if get_bill_pi:
			sync_qb_journal_entry_against_pi(get_bill_pi)

def validate_pi_payment(get_qb_billpayment):
	paid_pi = []
	for entries in get_qb_billpayment:
		for linked_txn in entries['Line']:
			has_bank_ref = entries.get('CheckPayment').get('BankAccountRef') if entries.get('CheckPayment').get('BankAccountRef') else ''
			if has_bank_ref:
				paid_pi.append({
					"Id": entries.get('Id') + "-" +'PI'+"-"+ linked_txn.get('LinkedTxn')[0].get('TxnId'),
					"Type" : linked_txn.get('LinkedTxn')[0].get('TxnType'),
					"ExchangeRate" :entries.get('ExchangeRate'),
					"Amount": linked_txn.get('Amount')*entries.get('ExchangeRate'),
					"TxnDate" : entries.get('TxnDate'),
					"PayType" :entries.get('PayType'),
					"qb_account_id": entries.get('CheckPayment').get('BankAccountRef').get('value'),
					"qb_pi_id": linked_txn.get('LinkedTxn')[0].get('TxnId'),
					'paid_amount': linked_txn.get('Amount'),
					"doc_no": entries.get("DocNumber")
					})
	return paid_pi

def sync_qb_journal_entry_against_pi(get_bill_pi):
	quickbooks_settings = frappe.get_doc("Quickbooks Settings", "Quickbooks Settings")
	for bill_payment in get_bill_pi:
		try:
			if not frappe.db.get_value("Payment Entry", {"quickbooks_payment_id": bill_payment.get('Id')}, "name"):
				create_payment_entry_pi(bill_payment, quickbooks_settings)
		except Exception, e:
			make_quickbooks_log(title=e.message, status="Error", method="sync_qb_journal_entry_against_pi", message=frappe.get_traceback(),
						request_data=bill_payment, exception=True)



def create_payment_entry_pi(bill_payment, quickbooks_settings):
	""" create payment entry against Purchase Invoice """

	invoice_name =frappe.db.get_value("Purchase Invoice", {"quickbooks_purchase_invoice_id": bill_payment.get('qb_pi_id')}, "name")
	account_ref = get_account_detail(bill_payment.get('qb_account_id'))
	if invoice_name:
		ref_doc = frappe.get_doc("Purchase Invoice", invoice_name)
		pi_pe = frappe.new_doc("Payment Entry")
		pi_pe.naming_series = "PI-PE-QB-"
		pi_pe.quickbooks_invoice_reference_no = ref_doc.get('quickbooks_bill_no')
		pi_pe.quickbooks_payment_reference_no = bill_payment.get('doc_no')
		pi_pe.posting_date = bill_payment.get('TxnDate')
		pi_pe.quickbooks_payment_id = bill_payment.get('Id')
		pi_pe.payment_type = "Pay"
		pi_pe.party_type = "Supplier"
		pi_pe.party = ref_doc.supplier_name
		pi_pe.paid_to = ref_doc.get("credit_to")
		pi_pe.received_amount = flt(bill_payment.get('paid_amount'), pi_pe.precision('received_amount'))
		pi_pe.target_exchange_rate = bill_payment.get('ExchangeRate')
		pi_pe.base_received_amount =  flt(bill_payment.get('paid_amount') * bill_payment.get('ExchangeRate'), pi_pe.precision('base_received_amount'))
		pi_pe.base_paid_amount = flt(bill_payment.get('paid_amount') * bill_payment.get('ExchangeRate'), pi_pe.precision('base_paid_amount'))
		pi_pe.allocate_payment_amount = 1
		pi_pe.reference_no = bill_payment.get('Type')
		pi_pe.reference_date = bill_payment.get('TxnDate')

		get_accounts_pi(pi_pe, ref_doc, bill_payment, quickbooks_settings)
		get_reference(dt= "Purchase Invoice", pay_entry_obj= pi_pe, ref_doc= ref_doc, ref_pay= bill_payment, quickbooks_settings= quickbooks_settings)
		get_deduction(dt= "Purchase Invoice", pay_entry_obj= pi_pe, ref_doc= ref_doc, ref_pay= bill_payment, quickbooks_settings= quickbooks_settings)
		pi_pe.flags.ignore_mandatory = True
		pi_pe.save(ignore_permissions=True)
		pi_pe.submit()
		frappe.db.commit()

def get_accounts_pi(pi_pe, ref_doc, bill_payment, quickbooks_settings):
	""" set exchange rate and payment amount , when payment is done in multi currency, apart from system currency """

	company_name = quickbooks_settings.select_company
	company_currency = frappe.db.get_value("Company", {"name": company_name}, "default_currency")
	account_ref = get_account_detail(bill_payment.get('qb_account_id'))
	pi_pe.paid_from = account_ref.get('name')
	if account_ref.get('account_currency') == company_currency:
		pi_pe.source_exchange_rate = 1
		pi_pe.paid_amount = flt(bill_payment.get('paid_amount') * bill_payment.get('ExchangeRate'), pi_pe.precision('paid_amount'))
	else:
		pi_pe.source_exchange_rate = bill_payment.get('ExchangeRate')
		pi_pe.paid_amount = flt(bill_payment.get('paid_amount') , pi_pe.precision('paid_amount'))



def get_reference(dt= None, pay_entry_obj= None, ref_doc= None, ref_pay= None, quickbooks_settings= None):
	""" get reference of Invoices for which payment is done. """

	account = pay_entry_obj.append("references", {})
	account.reference_doctype = dt
	account.reference_name = ref_doc.get('name')
	account.total_amount = flt(ref_doc.get('grand_total'), account.precision('total_amount'))
	account.allocated_amount = flt(ref_pay.get('paid_amount'), account.precision('allocated_amount'))


def get_deduction(dt= None, pay_entry_obj= None, ref_doc= None, ref_pay= None, quickbooks_settings= None):
	"""	calculate deduction for Multi currency gain and loss """
	if dt == "Purchase Invoice":
		total_allocated_amount = flt(ref_pay.get("paid_amount") * ref_doc.get('conversion_rate'))
		recevied_amount = flt(ref_pay.get("paid_amount") * ref_pay.get('ExchangeRate'))
		deduction_amount = recevied_amount - total_allocated_amount
	else:
		total_allocated_amount = flt(flt(ref_pay.get("paid_amount")) * flt(ref_doc.get('conversion_rate')))
		deduction_amount = total_allocated_amount - pay_entry_obj.base_received_amount

	if round(deduction_amount, 2):
		deduction = pay_entry_obj.append("deductions",{})
		deduction.account = quickbooks_settings.profit_loss_account
		deduction.cost_center = frappe.db.get_value("Company",{"name": quickbooks_settings.select_company },"cost_center")
		deduction.amount = deduction_amount

def get_account_detail(quickbooks_account_id):
	""" account for payment """
	return frappe.db.get_value("Account", {"quickbooks_account_id": quickbooks_account_id}, ["name", "account_currency"], as_dict=1)
