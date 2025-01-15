import http.client
import json
import logging
from io import BytesIO
from urllib import parse
from urllib.request import HTTPHandler, HTTPSHandler, OpenerDirector, Request, install_opener

from rdflib.namespace import RDF, Namespace
from urllib3.response import HTTPResponse

logger = logging.getLogger(__name__)

AS2 = Namespace("https://www.w3.org/ns/activitystreams#")
LDP = Namespace("http://www.w3.org/ns/ldp#")
SEC = Namespace("https://w3id.org/security#")
SEC_V1 = Namespace("https://w3id.org/security/v1#")
W3ID = Namespace("https://w3id.org/identity/v1#")
SCHEMA = Namespace("https://schema.org/")
MASTODON = Namespace("http://joinmastodon.org/ns#")
PURL = Namespace("https://purl.org/wytchspace/ns/ap/1.0#")
PURL_RELATIONSHIP = Namespace("http://purl.org/vocab/relationship#")


AS_EXTENSIONS = {AS2.Hashtag, AS2.manuallyApprovesFollowers, AS2.movedTo, AS2.sensitive}


SEC_CONTEXT_DOCUMENT = {
    "@context": {
        "id": "@id",
        "type": "@type",
        "dc": "http://purl.org/dc/terms/",
        "sec": "https://w3id.org/security#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "EcdsaKoblitzSignature2016": "sec:EcdsaKoblitzSignature2016",
        "Ed25519Signature2018": "sec:Ed25519Signature2018",
        "EncryptedMessage": "sec:EncryptedMessage",
        "GraphSignature2012": "sec:GraphSignature2012",
        "LinkedDataSignature2015": "sec:LinkedDataSignature2015",
        "LinkedDataSignature2016": "sec:LinkedDataSignature2016",
        "CryptographicKey": "sec:Key",
        "authenticationTag": "sec:authenticationTag",
        "canonicalizationAlgorithm": "sec:canonicalizationAlgorithm",
        "cipherAlgorithm": "sec:cipherAlgorithm",
        "cipherData": "sec:cipherData",
        "cipherKey": "sec:cipherKey",
        "created": {"@id": "dc:created", "@type": "xsd:dateTime"},
        "creator": {"@id": "dc:creator", "@type": "@id"},
        "digestAlgorithm": "sec:digestAlgorithm",
        "digestValue": "sec:digestValue",
        "domain": "sec:domain",
        "encryptionKey": "sec:encryptionKey",
        "expiration": {"@id": "sec:expiration", "@type": "xsd:dateTime"},
        "expires": {"@id": "sec:expiration", "@type": "xsd:dateTime"},
        "initializationVector": "sec:initializationVector",
        "iterationCount": "sec:iterationCount",
        "nonce": "sec:nonce",
        "normalizationAlgorithm": "sec:normalizationAlgorithm",
        "owner": {"@id": "sec:owner", "@type": "@id"},
        "password": "sec:password",
        "privateKey": {"@id": "sec:privateKey", "@type": "@id"},
        "privateKeyPem": "sec:privateKeyPem",
        "publicKey": {"@id": "sec:publicKey", "@type": "@id"},
        "publicKeyBase58": "sec:publicKeyBase58",
        "publicKeyPem": "sec:publicKeyPem",
        "publicKeyWif": "sec:publicKeyWif",
        "publicKeyService": {"@id": "sec:publicKeyService", "@type": "@id"},
        "revoked": {"@id": "sec:revoked", "@type": "xsd:dateTime"},
        "salt": "sec:salt",
        "signature": "sec:signature",
        "signatureAlgorithm": "sec:signingAlgorithm",
        "signatureValue": "sec:signatureValue",
    }
}

AS_CONTEXT_DOCUMENT = {
    "@context": {
        "@vocab": "_:",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "as": "https://www.w3.org/ns/activitystreams#",
        "ldp": "http://www.w3.org/ns/ldp#",
        "vcard": "http://www.w3.org/2006/vcard/ns#",
        "id": "@id",
        "type": "@type",
        "Accept": "as:Accept",
        "Activity": "as:Activity",
        "IntransitiveActivity": "as:IntransitiveActivity",
        "Add": "as:Add",
        "Announce": "as:Announce",
        "Application": "as:Application",
        "Arrive": "as:Arrive",
        "Article": "as:Article",
        "Audio": "as:Audio",
        "Block": "as:Block",
        "Collection": "as:Collection",
        "CollectionPage": "as:CollectionPage",
        "Relationship": "as:Relationship",
        "Create": "as:Create",
        "Delete": "as:Delete",
        "Dislike": "as:Dislike",
        "Document": "as:Document",
        "Event": "as:Event",
        "Follow": "as:Follow",
        "Flag": "as:Flag",
        "Group": "as:Group",
        "Ignore": "as:Ignore",
        "Image": "as:Image",
        "Invite": "as:Invite",
        "Join": "as:Join",
        "Leave": "as:Leave",
        "Like": "as:Like",
        "Link": "as:Link",
        "Mention": "as:Mention",
        "Note": "as:Note",
        "Object": "as:Object",
        "Offer": "as:Offer",
        "OrderedCollection": "as:OrderedCollection",
        "OrderedCollectionPage": "as:OrderedCollectionPage",
        "Organization": "as:Organization",
        "Page": "as:Page",
        "Person": "as:Person",
        "Place": "as:Place",
        "Profile": "as:Profile",
        "Question": "as:Question",
        "Reject": "as:Reject",
        "Remove": "as:Remove",
        "Service": "as:Service",
        "TentativeAccept": "as:TentativeAccept",
        "TentativeReject": "as:TentativeReject",
        "Tombstone": "as:Tombstone",
        "Undo": "as:Undo",
        "Update": "as:Update",
        "Video": "as:Video",
        "View": "as:View",
        "Listen": "as:Listen",
        "Read": "as:Read",
        "Move": "as:Move",
        "Travel": "as:Travel",
        "IsFollowing": "as:IsFollowing",
        "IsFollowedBy": "as:IsFollowedBy",
        "IsContact": "as:IsContact",
        "IsMember": "as:IsMember",
        "subject": {"@id": "as:subject", "@type": "@id"},
        "relationship": {"@id": "as:relationship", "@type": "@id"},
        "actor": {"@id": "as:actor", "@type": "@id"},
        "attributedTo": {"@id": "as:attributedTo", "@type": "@id"},
        "attachment": {"@id": "as:attachment", "@type": "@id"},
        "bcc": {"@id": "as:bcc", "@type": "@id"},
        "bto": {"@id": "as:bto", "@type": "@id"},
        "cc": {"@id": "as:cc", "@type": "@id"},
        "context": {"@id": "as:context", "@type": "@id"},
        "current": {"@id": "as:current", "@type": "@id"},
        "first": {"@id": "as:first", "@type": "@id"},
        "generator": {"@id": "as:generator", "@type": "@id"},
        "icon": {"@id": "as:icon", "@type": "@id"},
        "image": {"@id": "as:image", "@type": "@id"},
        "inReplyTo": {"@id": "as:inReplyTo", "@type": "@id"},
        "items": {"@id": "as:items", "@type": "@id"},
        "instrument": {"@id": "as:instrument", "@type": "@id"},
        "orderedItems": {"@id": "as:items", "@type": "@id", "@container": "@list"},
        "last": {"@id": "as:last", "@type": "@id"},
        "location": {"@id": "as:location", "@type": "@id"},
        "next": {"@id": "as:next", "@type": "@id"},
        "object": {"@id": "as:object", "@type": "@id"},
        "oneOf": {"@id": "as:oneOf", "@type": "@id"},
        "anyOf": {"@id": "as:anyOf", "@type": "@id"},
        "closed": {"@id": "as:closed", "@type": "xsd:dateTime"},
        "origin": {"@id": "as:origin", "@type": "@id"},
        "accuracy": {"@id": "as:accuracy", "@type": "xsd:float"},
        "prev": {"@id": "as:prev", "@type": "@id"},
        "preview": {"@id": "as:preview", "@type": "@id"},
        "replies": {"@id": "as:replies", "@type": "@id"},
        "result": {"@id": "as:result", "@type": "@id"},
        "audience": {"@id": "as:audience", "@type": "@id"},
        "partOf": {"@id": "as:partOf", "@type": "@id"},
        "tag": {"@id": "as:tag", "@type": "@id"},
        "target": {"@id": "as:target", "@type": "@id"},
        "to": {"@id": "as:to", "@type": "@id"},
        "url": {"@id": "as:url", "@type": "@id"},
        "altitude": {"@id": "as:altitude", "@type": "xsd:float"},
        "content": "as:content",
        "contentMap": {"@id": "as:content", "@container": "@language"},
        "name": "as:name",
        "nameMap": {"@id": "as:name", "@container": "@language"},
        "duration": {"@id": "as:duration", "@type": "xsd:duration"},
        "endTime": {"@id": "as:endTime", "@type": "xsd:dateTime"},
        "height": {"@id": "as:height", "@type": "xsd:nonNegativeInteger"},
        "href": {"@id": "as:href", "@type": "@id"},
        "hreflang": "as:hreflang",
        "latitude": {"@id": "as:latitude", "@type": "xsd:float"},
        "longitude": {"@id": "as:longitude", "@type": "xsd:float"},
        "mediaType": "as:mediaType",
        "published": {"@id": "as:published", "@type": "xsd:dateTime"},
        "radius": {"@id": "as:radius", "@type": "xsd:float"},
        "rel": "as:rel",
        "startIndex": {"@id": "as:startIndex", "@type": "xsd:nonNegativeInteger"},
        "startTime": {"@id": "as:startTime", "@type": "xsd:dateTime"},
        "summary": "as:summary",
        "summaryMap": {"@id": "as:summary", "@container": "@language"},
        "totalItems": {"@id": "as:totalItems", "@type": "xsd:nonNegativeInteger"},
        "units": "as:units",
        "updated": {"@id": "as:updated", "@type": "xsd:dateTime"},
        "width": {"@id": "as:width", "@type": "xsd:nonNegativeInteger"},
        "describes": {"@id": "as:describes", "@type": "@id"},
        "formerType": {"@id": "as:formerType", "@type": "@id"},
        "deleted": {"@id": "as:deleted", "@type": "xsd:dateTime"},
        "inbox": {"@id": "ldp:inbox", "@type": "@id"},
        "outbox": {"@id": "as:outbox", "@type": "@id"},
        "following": {"@id": "as:following", "@type": "@id"},
        "followers": {"@id": "as:followers", "@type": "@id"},
        "streams": {"@id": "as:streams", "@type": "@id"},
        "preferredUsername": "as:preferredUsername",
        "endpoints": {"@id": "as:endpoints", "@type": "@id"},
        "uploadMedia": {"@id": "as:uploadMedia", "@type": "@id"},
        "proxyUrl": {"@id": "as:proxyUrl", "@type": "@id"},
        "liked": {"@id": "as:liked", "@type": "@id"},
        "oauthAuthorizationEndpoint": {"@id": "as:oauthAuthorizationEndpoint", "@type": "@id"},
        "oauthTokenEndpoint": {"@id": "as:oauthTokenEndpoint", "@type": "@id"},
        "provideClientKey": {"@id": "as:provideClientKey", "@type": "@id"},
        "signClientKey": {"@id": "as:signClientKey", "@type": "@id"},
        "sharedInbox": {"@id": "as:sharedInbox", "@type": "@id"},
        "Public": {"@id": "as:Public", "@type": "@id"},
        "source": "as:source",
        "likes": {"@id": "as:likes", "@type": "@id"},
        "shares": {"@id": "as:shares", "@type": "@id"},
        "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
    }
}


SCHEMA_DEFINITIONS = {
    "unknown": {
        "contentType": "application/ld+json",
        "documentUrl": "unknown",
        "contextUrl": None,
        "document": {
            "@context": {},
        },
    },
    "www.w3.org/ns/activitystreams": {
        "contentType": "application/ld+json",
        "documentUrl": "http://www.w3.org/ns/activitystreams",
        "contextUrl": None,
        "document": AS_CONTEXT_DOCUMENT,
    },
    "w3id.org/security/v1": {
        "contentType": "application/ld+json",
        "documentUrl": "https://w3id.org/security#",
        "contextUrl": None,
        "document": SEC_CONTEXT_DOCUMENT,
    },
    "w3id.org/security": {
        "contentType": "application/ld+json",
        "documentUrl": "https://w3id.org/security",
        "contextUrl": None,
        "document": SEC_CONTEXT_DOCUMENT,
    },
    "w3id.org/identity/v1": {
        "contentType": "application/ld+json",
        "documentUrl": "http://w3id.org/identity/v1",
        "contextUrl": None,
        "document": {
            "@context": {
                "id": "@id",
                "type": "@type",
                "cred": "https://w3id.org/credentials#",
                "dc": "http://purl.org/dc/terms/",
                "identity": "https://w3id.org/identity#",
                "perm": "https://w3id.org/permissions#",
                "ps": "https://w3id.org/payswarm#",
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                "sec": "https://w3id.org/security#",
                "schema": "http://schema.org/",
                "xsd": "http://www.w3.org/2001/XMLSchema#",
                "Group": "https://www.w3.org/ns/activitystreams#Group",
                "claim": {"@id": "cred:claim", "@type": "@id"},
                "credential": {"@id": "cred:credential", "@type": "@id"},
                "issued": {"@id": "cred:issued", "@type": "xsd:dateTime"},
                "issuer": {"@id": "cred:issuer", "@type": "@id"},
                "recipient": {"@id": "cred:recipient", "@type": "@id"},
                "Credential": "cred:Credential",
                "CryptographicKeyCredential": "cred:CryptographicKeyCredential",
                "about": {"@id": "schema:about", "@type": "@id"},
                "address": {"@id": "schema:address", "@type": "@id"},
                "addressCountry": "schema:addressCountry",
                "addressLocality": "schema:addressLocality",
                "addressRegion": "schema:addressRegion",
                "comment": "rdfs:comment",
                "created": {"@id": "dc:created", "@type": "xsd:dateTime"},
                "creator": {"@id": "dc:creator", "@type": "@id"},
                "description": "schema:description",
                "email": "schema:email",
                "familyName": "schema:familyName",
                "givenName": "schema:givenName",
                "image": {"@id": "schema:image", "@type": "@id"},
                "label": "rdfs:label",
                "name": "schema:name",
                "postalCode": "schema:postalCode",
                "streetAddress": "schema:streetAddress",
                "title": "dc:title",
                "url": {"@id": "schema:url", "@type": "@id"},
                "Person": "schema:Person",
                "PostalAddress": "schema:PostalAddress",
                "Organization": "schema:Organization",
                "identityService": {"@id": "identity:identityService", "@type": "@id"},
                "idp": {"@id": "identity:idp", "@type": "@id"},
                "Identity": "identity:Identity",
                "paymentProcessor": "ps:processor",
                "preferences": {"@id": "ps:preferences", "@type": "@vocab"},
                "cipherAlgorithm": "sec:cipherAlgorithm",
                "cipherData": "sec:cipherData",
                "cipherKey": "sec:cipherKey",
                "digestAlgorithm": "sec:digestAlgorithm",
                "digestValue": "sec:digestValue",
                "domain": "sec:domain",
                "expires": {"@id": "sec:expiration", "@type": "xsd:dateTime"},
                "initializationVector": "sec:initializationVector",
                "member": {"@id": "schema:member", "@type": "@id"},
                "memberOf": {"@id": "schema:memberOf", "@type": "@id"},
                "nonce": "sec:nonce",
                "normalizationAlgorithm": "sec:normalizationAlgorithm",
                "owner": {"@id": "sec:owner", "@type": "@id"},
                "password": "sec:password",
                "privateKey": {"@id": "sec:privateKey", "@type": "@id"},
                "privateKeyPem": "sec:privateKeyPem",
                "publicKey": {"@id": "sec:publicKey", "@type": "@id"},
                "publicKeyPem": "sec:publicKeyPem",
                "publicKeyService": {"@id": "sec:publicKeyService", "@type": "@id"},
                "revoked": {"@id": "sec:revoked", "@type": "xsd:dateTime"},
                "signature": "sec:signature",
                "signatureAlgorithm": "sec:signatureAlgorithm",
                "signatureValue": "sec:signatureValue",
                "CryptographicKey": "sec:Key",
                "EncryptedMessage": "sec:EncryptedMessage",
                "GraphSignature2012": "sec:GraphSignature2012",
                "LinkedDataSignature2015": "sec:LinkedDataSignature2015",
                "accessControl": {"@id": "perm:accessControl", "@type": "@id"},
                "writePermission": {"@id": "perm:writePermission", "@type": "@id"},
            }
        },
    },
    "www.w3.org/ns/did/v1": {
        "contentType": "application/ld+json",
        "documentUrl": "www.w3.org/ns/did/v1",
        "contextUrl": None,
        "document": {
            "@context": {
                "@protected": True,
                "id": "@id",
                "type": "@type",
                "alsoKnownAs": {
                    "@id": "https://www.w3.org/ns/activitystreams#alsoKnownAs",
                    "@type": "@id",
                },
                "assertionMethod": {
                    "@id": "https://w3id.org/security#assertionMethod",
                    "@type": "@id",
                    "@container": "@set",
                },
                "authentication": {
                    "@id": "https://w3id.org/security#authenticationMethod",
                    "@type": "@id",
                    "@container": "@set",
                },
                "capabilityDelegation": {
                    "@id": "https://w3id.org/security#capabilityDelegationMethod",
                    "@type": "@id",
                    "@container": "@set",
                },
                "capabilityInvocation": {
                    "@id": "https://w3id.org/security#capabilityInvocationMethod",
                    "@type": "@id",
                    "@container": "@set",
                },
                "controller": {
                    "@id": "https://w3id.org/security#controller",
                    "@type": "@id",
                },
                "keyAgreement": {
                    "@id": "https://w3id.org/security#keyAgreementMethod",
                    "@type": "@id",
                    "@container": "@set",
                },
                "service": {
                    "@id": "https://www.w3.org/ns/did#service",
                    "@type": "@id",
                    "@context": {
                        "@protected": True,
                        "id": "@id",
                        "type": "@type",
                        "serviceEndpoint": {
                            "@id": "https://www.w3.org/ns/did#serviceEndpoint",
                            "@type": "@id",
                        },
                    },
                },
                "verificationMethod": {
                    "@id": "https://w3id.org/security#verificationMethod",
                    "@type": "@id",
                },
            }
        },
    },
    "w3id.org/security/data-integrity/v1": {
        "contentType": "application/ld+json",
        "documentUrl": "https://w3id.org/security/data-integrity/v1",
        "contextUrl": None,
        "document": {
            "@context": {
                "id": "@id",
                "type": "@type",
                "@protected": True,
                "proof": {
                    "@id": "https://w3id.org/security#proof",
                    "@type": "@id",
                    "@container": "@graph",
                },
                "DataIntegrityProof": {
                    "@id": "https://w3id.org/security#DataIntegrityProof",
                    "@context": {
                        "@protected": True,
                        "id": "@id",
                        "type": "@type",
                        "challenge": "https://w3id.org/security#challenge",
                        "created": {
                            "@id": "http://purl.org/dc/terms/created",
                            "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
                        },
                        "domain": "https://w3id.org/security#domain",
                        "expires": {
                            "@id": "https://w3id.org/security#expiration",
                            "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
                        },
                        "nonce": "https://w3id.org/security#nonce",
                        "proofPurpose": {
                            "@id": "https://w3id.org/security#proofPurpose",
                            "@type": "@vocab",
                            "@context": {
                                "@protected": True,
                                "id": "@id",
                                "type": "@type",
                                "assertionMethod": {
                                    "@id": "https://w3id.org/security#assertionMethod",
                                    "@type": "@id",
                                    "@container": "@set",
                                },
                                "authentication": {
                                    "@id": "https://w3id.org/security#authenticationMethod",
                                    "@type": "@id",
                                    "@container": "@set",
                                },
                                "capabilityInvocation": {
                                    "@id": "https://w3id.org/security#capabilityInvocationMethod",
                                    "@type": "@id",
                                    "@container": "@set",
                                },
                                "capabilityDelegation": {
                                    "@id": "https://w3id.org/security#capabilityDelegationMethod",
                                    "@type": "@id",
                                    "@container": "@set",
                                },
                                "keyAgreement": {
                                    "@id": "https://w3id.org/security#keyAgreementMethod",
                                    "@type": "@id",
                                    "@container": "@set",
                                },
                            },
                        },
                        "cryptosuite": "https://w3id.org/security#cryptosuite",
                        "proofValue": {
                            "@id": "https://w3id.org/security#proofValue",
                            "@type": "https://w3id.org/security#multibase",
                        },
                        "verificationMethod": {
                            "@id": "https://w3id.org/security#verificationMethod",
                            "@type": "@id",
                        },
                    },
                },
            }
        },
    },
    "w3id.org/security/multikey/v1": {
        "contentType": "application/ld+json",
        "documentUrl": "https://w3id.org/security/multikey/v1",
        "contextUrl": None,
        "document": {
            "@context": {
                "id": "@id",
                "type": "@type",
                "@protected": True,
                "Multikey": {
                    "@id": "https://w3id.org/security#Multikey",
                    "@context": {
                        "@protected": True,
                        "id": "@id",
                        "type": "@type",
                        "controller": {
                            "@id": "https://w3id.org/security#controller",
                            "@type": "@id",
                        },
                        "revoked": {
                            "@id": "https://w3id.org/security#revoked",
                            "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
                        },
                        "expires": {
                            "@id": "https://w3id.org/security#expiration",
                            "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
                        },
                        "publicKeyMultibase": {
                            "@id": "https://w3id.org/security#publicKeyMultibase",
                            "@type": "https://w3id.org/security#multibase",
                        },
                        "secretKeyMultibase": {
                            "@id": "https://w3id.org/security#secretKeyMultibase",
                            "@type": "https://w3id.org/security#multibase",
                        },
                    },
                },
            },
        },
    },
    "*/schemas/litepub-0.1.jsonld": {
        "contentType": "application/ld+json",
        "documentUrl": "http://w3id.org/security/v1",
        "contextUrl": None,
        "document": {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                {
                    "Emoji": "toot:Emoji",
                    "Hashtag": "as:Hashtag",
                    "PropertyValue": "schema:PropertyValue",
                    "atomUri": "ostatus:atomUri",
                    "conversation": {"@id": "ostatus:conversation", "@type": "@id"},
                    "discoverable": "toot:discoverable",
                    "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
                    "capabilities": "litepub:capabilities",
                    "ostatus": "http://ostatus.org#",
                    "schema": "http://schema.org#",
                    "toot": "http://joinmastodon.org/ns#",
                    "misskey": "https://misskey-hub.net/ns#",
                    "fedibird": "http://fedibird.com/ns#",
                    "value": "schema:value",
                    "sensitive": "as:sensitive",
                    "litepub": "http://litepub.social/ns#",
                    "invisible": "litepub:invisible",
                    "directMessage": "litepub:directMessage",
                    "listMessage": {"@id": "litepub:listMessage", "@type": "@id"},
                    "quoteUrl": "as:quoteUrl",
                    "quoteUri": "fedibird:quoteUri",
                    "oauthRegistrationEndpoint": {
                        "@id": "litepub:oauthRegistrationEndpoint",
                        "@type": "@id",
                    },
                    "EmojiReact": "litepub:EmojiReact",
                    "ChatMessage": "litepub:ChatMessage",
                    "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
                    "vcard": "http://www.w3.org/2006/vcard/ns#",
                    "formerRepresentations": "litepub:formerRepresentations",
                },
            ]
        },
    },
    "joinmastodon.org/ns": {
        "contentType": "application/ld+json",
        "documentUrl": "http://joinmastodon.org/ns",
        "contextUrl": None,
        "document": {
            "@context": {
                "toot": "http://joinmastodon.org/ns#",
                "discoverable": "toot:discoverable",
                "devices": "toot:devices",
                "featured": "toot:featured",
                "featuredTags": "toot:featuredTags",
            },
        },
    },
    "funkwhale.audio/ns": {
        "contentType": "application/ld+json",
        "documentUrl": "http://funkwhale.audio/ns",
        "contextUrl": None,
        "document": {
            "@context": {
                "id": "@id",
                "type": "@type",
                "as": "https://www.w3.org/ns/activitystreams#",
                "schema": "http://schema.org#",
                "fw": "https://funkwhale.audio/ns#",
                "xsd": "http://www.w3.org/2001/XMLSchema#",
                "Album": "fw:Album",
                "Track": "fw:Track",
                "Artist": "fw:Artist",
                "Library": "fw:Library",
                "bitrate": {"@id": "fw:bitrate", "@type": "xsd:nonNegativeInteger"},
                "size": {"@id": "fw:size", "@type": "xsd:nonNegativeInteger"},
                "position": {"@id": "fw:position", "@type": "xsd:nonNegativeInteger"},
                "disc": {"@id": "fw:disc", "@type": "xsd:nonNegativeInteger"},
                "library": {"@id": "fw:library", "@type": "@id"},
                "track": {"@id": "fw:track", "@type": "@id"},
                "cover": {"@id": "fw:cover", "@type": "as:Link"},
                "album": {"@id": "fw:album", "@type": "@id"},
                "artists": {"@id": "fw:artists", "@type": "@id", "@container": "@list"},
                "released": {"@id": "fw:released", "@type": "xsd:date"},
                "musicbrainzId": "fw:musicbrainzId",
                "license": {"@id": "fw:license", "@type": "@id"},
                "copyright": "fw:copyright",
                "category": "sc:category",
                "language": "sc:inLanguage",
            }
        },
    },
    "schema.org": {
        "contentType": "application/ld+json",
        "documentUrl": "https://schema.org/docs/jsonldcontext.json",
        "contextUrl": None,
        "document": {
            "@context": {
                "schema": "http://schema.org/",
                "PropertyValue": {"@id": "schema:PropertyValue"},
                "value": {"@id": "schema:value"},
            },
        },
    },
    "purl.org/wytchspace/ns/ap/1.0": {
        "contentType": "application/ld+json",
        "documentUrl": "https://purl.org/wytchspace/ns/ap/1.0",
        "contextUrl": None,
        "document": {
            "@context": {
                "wytch": "https://ns.wytch.space/ap/1.0.jsonld",
            },
        },
    },
}


def builtin_document_loader(url: str, options={}):
    pieces = parse.urlparse(url)
    try:
        assert pieces.hostname is not None
        key = pieces.hostname + pieces.path.rstrip("/")
        if key not in SCHEMA_DEFINITIONS:
            key = "*" + pieces.path.rstrip("/")
        return SCHEMA_DEFINITIONS[key]
    except AssertionError:
        logger.info(f"No host name for json-ld schema: {url!r}")
        return SCHEMA_DEFINITIONS["unknown"]
    except KeyError:
        logger.info(f"Ignoring unknown json-ld schema: {url!r}")
        return SCHEMA_DEFINITIONS["unknown"]


class LocalDocumentHandler(HTTPHandler, HTTPSHandler):
    """
    A HTTP handler that to get context documents directly, instead
    of loading from the web every time.
    """

    PROTECTED_URLS = [
        "www.w3.org/ns/activitystreams",
        "w3id.org/security/v1",
        "w3id.org/security",
        "w3id.org/identity/v1",
        "www.w3.org/ns/did/v1",
        "w3id.org/security/data-integrity/v1",
        "w3id.org/security/multikey/v1",
        "joinmastodon.org/ns",
        "funkwhale.audio/ns",
        "schema.org",
        "purl.org/wytchspace/ns/ap/1.0",
    ]

    @property
    def document_definitions_by_url(self):
        return {url: SCHEMA_DEFINITIONS[url]["document"] for url in self.PROTECTED_URLS}

    def _response_from_local_document(self, req, document) -> HTTPResponse:
        # See https://github.com/getsentry/responses/blob/master/responses/__init__.py
        # https://github.com/getsentry/responses/issues/691

        data = BytesIO()
        data.close()
        headers = {"Content-Type": "application/ld+json"}

        orig_response = HTTPResponse(
            body=data,
            msg=headers,
            preload_content=False,
        )
        status = 200

        body = BytesIO()
        body.write(json.dumps(document).encode("utf-8"))
        body.seek(0)

        return HTTPResponse(
            status=status,
            reason=http.client.responses.get(status, None),
            body=body,
            headers=headers,
            original_response=orig_response,
            preload_content=False,
            request_method=req.get_method(),
        )

    def http_open(self, req: Request) -> http.client.HTTPResponse:
        url = req.get_full_url().removeprefix("http://")
        document = self.document_definitions_by_url.get(url)

        if document is not None:
            return self._response_from_local_document(req, document)
        return super().http_open(req)

    def https_open(self, req: Request) -> http.client.HTTPResponse:

        url = req.get_full_url().removeprefix("https://")

        document = self.document_definitions_by_url.get(url)
        if document is not None:
            return self._response_from_local_document(req, document)

        return super().https_open(req)


def secure_rdflib():
    opener = OpenerDirector()
    opener.add_handler(LocalDocumentHandler())
    install_opener(opener)


__all__ = ["AS2", "LDP", "SEC", "SEC_V1", "W3ID", "SCHEMA", "MASTODON", "AS_EXTENSIONS", "RDF"]
