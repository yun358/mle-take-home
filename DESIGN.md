The AI tools used are Gemini for data profiling and custom label for benchmark, research and Claude for app coding, testing and feedback, drafting part of design.md, explanation and also review. 

Consumer cleans, stores each company info in Postgres database, with the natureOfBusiness as a pgvector embedding, it then acknowledges the message. FastAPI sends query to run the similarity search for the nearest neighbours of a company.


- Consumer:
	- getting data from RabbitMQ company-events queue. We don't make any changes to the RabbitMQ company-events queue, just keep it as durable without extra arguments.
	- data cleaning
		- capitalise all letters in registration numbers, strip spaces: `" syn-000949 "` → `SYN-000949`
		- consistent casing for "state", e.g., only first letters are capitalised: "kuala LUMPUR" -> "Kuala Lumpur"
		- duplicate data
			- base on registration number and updatedAt, if they are already the same or the updatedAt is older, just ack but don't upsert the data.
		- incomplete data
			- If natureOfBusiness doesn't exist, then just use name and industry for pgvector embeddings (most relevant data left).
			- if timestamp is missing, don't overwrite the data if company exists in database, if company doesn't exist in database, add the company to the database.
			- store companies without registration numbers in PostgresSQL table rejected_messages, since companies without registration numbers don't have enough relevant details to be stored in the main table too, at least in this dataset.
		- struck-off companies: since all of them were previously accessible, we keep the existing data in the database to allow access to their information in the portal, but flag them as struck-off.  
			- if company is struck off first before existing in database, but then full data with older timestamp for the same company is fed to the database, it remains with the struck-off flag, and its full details are not upserted.
		- updated data of the same company
			- ~~upsert all fields it if the timestamp is newer AND the data is different (because we have to precompute neighbours again if the data is actually updated). Also just update the timestamp even if other data fields remain the same.~~
				- ~~We need to reembed pgvector if the natureOfBusiness is updated, and recompute neighbours.~~
			- Don't upsert a field if the new value is "" or JSON null or "Unknown", missing registration number, non-text registration number, data is a string such as companyName = Foo;
			- Don't upsert purely numeric registration number
			- new messages (based on timestamp) will upsert data if the company exists in the database, but we do re-embedding only if the (usually) natureOfBusiness has changed. If company hasn't exist in database, upsert the data.
		- junk messages: ack and store in rejected-messages database.
		- timestamp format:
			- most timestamps use the ISO with offset format: "2026-08-14T09:00:00+08:00".
			 means 2026 august 14th, 9 am, UTC +8 timezone.
			- ~~convert ISO with Z to ISO with offset +8 .~~ timestampz just convert all timestamps to UTC
			- for ISO with no timezones, assume Malaysian time (as Malaysian time timestamps are most common, 2428 out of 2507 timestamps, only 14 with no timezone).
			- Integer: converted to timestampz
			- missing timestamp: NULL, treat it as oldest timestamp compared to other timestamps.
	
	- a message is acked after committing it to database, but if one of the process fails, say embedding model fails, the changes to database is rolled back from the database before committing to the database as permanent, and the message is requeued.
		
	- embedding and storing messages (of company infos) from RabbitMQ queue in PostgreSQL database (including the natureOfBusiness as pgvector)
		- we use paraphrase-multilingual-MiniLM-L12-v2 (official QUINT8 ONNX), best model we have tried so far for this dataset, beats BAAI/bge-m3 on custom benchmark (custom label). The metric is Precision@4: out of the top 4 recommended companies which ones have the same label.
		- Schemas:
			- in the code
	- ~~precomputing neighbours for each company and storing them in the database~~
	- ack each message after committing to database
- Service that the portal calls:
	- retrieval of neighbours (similar companies) from the PostgreSQL database, then sorting them by most similar first, and sending them to the OneCredit portal
	- seeded randomness for top tied-neighbours ~~if there are more than 4 top neighbours~~ of a company with the exact same natureOfBusiness. We can do this if the top neighbours have the same similarity score to the query company.
- Test Cases:
	- test the cleaning function works for all its functionalities
	- test that junk messages are processed
	- test timestamp converter works accurately
	- test messy field values are handled correctly
		- standardising letter case for 'state' field
		- dealing with missing values
		- dealing with extra fields
	- test that text embedding works correctly
		- embed description if it exists
		- no description -> name and industry
		- no description, no industry -> just name
	- test database updating
	- test dealing with struck-off messages
	- test consumer
		- bad message stored in rejected_messages
		- ack happens after database write
	- test the api
		- order results by most similar
		- invalid id sends error 400
		- database down sends error 503
		- **include any other potential errors**
	 - ~~test precomputing~~
		 - ~~how much does precomputed results differ from live query results?~~

---

Assumptions:

- struck-off companies are kept because the user expects to find all companies, but they are not in any recommendations
- timestamp with no timezone are assumed as Malaysian time as almost every timestamp is so
- missing or unparseable timestamp is set as older than any other timestamp, to not overwrite data with real timestamps
- updatedAt decides latest version of a company's data instead of message arrival time
- for companies without description, assume that name and industry provide the most context for embedding
- exact similarity of embeddings (cosine distance) to query company implies recommended companies have the same exact descriptions

---

What you would change to handle 10x the volume:

Since all the businesses are already stored in the database, we can pre-compute the similarity searches and store the registration numbers of most similar neighbours for each company in a sorted list (sorted by similarity score).

Hence when query is sent, similar neighbours are immediately retrieved from the list instead of doing Exact Nearest Neighbour search each time, which is fine for a small dataset, but slow at a for large scale data. 

We can also do Approximate Nearest Neighbour search, such as Hierarchical Navigable Small World, we limit our search scope to a portion of the data, with slight tradeoff in retrieval accuracy.

If we are also doing precomputing of neighbours of a company, say company A, and that company's natureOfBusiness detail is update, we have to recompute its list of neighbours. We can do Exact Nearest Neighbour search, and also use the new similarity scores between the updated company and every other company, to update every other company's list of neighbours:
- if the list already includes A, then check if the position of A needs to be switched, or removed. if A is removed, we do have to find a replacement, I suppose we can use ANN for that too.
- if the list hasn't include A, check if distance between A and current company B, d(A,B) is closer than the distance between B and its farthest neighbour C, d(B,C). If true, add A to the list and remove C.
- Perhaps there are other edge cases.

Also, we can use several API processes or servers, and a load balancer. The load balancer will split requests across multiple servers, to not overload any individual servers.

---

Model choice: paired t-test comparing BAAI bge-m3 to paraphrase-multilingual-MiniLM-L12-v2 (our current model), using custom labels, our current model scores on Precision@4 compared to bge-m3 (0.985 vs 0.934), with p-value < 0.05, and latency wise about 16x faster. We can also do the same test with other models like EmbeddingGemma2.

---


What's left:
- try out precompute of list of neighbours and test latency
- re-embedding with new models, perform model versioning with different models






